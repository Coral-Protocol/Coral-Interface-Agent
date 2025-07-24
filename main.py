import urllib.parse
from dotenv import load_dotenv
import os
import json
import asyncio
import logging
from typing import List, Dict, Any, Optional
from langchain.chat_models import init_chat_model
from langchain.prompts import ChatPromptTemplate
from langchain_mcp_adapters.client import MultiServerMCPClient
from langchain.agents import create_tool_calling_agent, AgentExecutor
from langchain.tools import Tool
import traceback

logging.basicConfig(level=logging.INFO, format="%(asctime)s - %(name)s - %(levelname)s - %(message)s")
logger = logging.getLogger(__name__)

def load_config() -> Dict[str, Any]:
    """Load and validate environment variables."""
    if os.getenv("CORAL_ORCHESTRATION_RUNTIME") not in ("docker", "executable"):
        load_dotenv()
    
    config = {
        "runtime": os.getenv("CORAL_ORCHESTRATION_RUNTIME", "devmode"),
        "coral_sse_url": os.getenv("CORAL_SSE_URL"),
        "agent_id": os.getenv("CORAL_AGENT_ID"),
        "model_name": os.getenv("MODEL_NAME"),
        "model_provider": os.getenv("MODEL_PROVIDER"),
        "api_key": os.getenv("API_KEY"),
        "model_temperature": float(os.getenv("MODEL_TEMPERATURE", 0.7)),
        "model_token": int(os.getenv("MODEL_TOKEN", 2048)),
        "base_url": os.getenv("BASE_URL")
    }
    
    required_fields = ["coral_sse_url", "agent_id", "model_name", "model_provider", "api_key"]
    missing = [field for field in required_fields if not config[field]]
    if missing:
        raise ValueError(f"Missing required environment variables: {', '.join(missing)}")
    
    return config

def get_tools_description(tools: List[Tool]) -> str:
    """Generate a string description of tools and their schemas."""
    return "\n".join(
        f"Tool: {tool.name}, Schema: {json.dumps(tool.args).replace('{', '{{').replace('}', '}}')}"
        for tool in tools
    )

async def ask_human_tool(question: str) -> str:
    """Ask a question to the human user and return their response."""
    logger.info(f"Agent asks: {question}")
    response = input("Your response: ").strip()
    if not response:
        response = "No response provided"
    logger.info(f"User responded: {response}")
    return response

async def create_agent(coral_tools: List[Tool], agent_tools: List[Any], runtime: str) -> AgentExecutor:
    """Create and configure the agent with tools and prompt."""
    coral_tools_description = get_tools_description(coral_tools)
    
    if runtime in ("docker", "executable"):
        agent_tools_for_description = [tool for tool in coral_tools if tool.name in agent_tools]
        agent_tools_description = get_tools_description(agent_tools_for_description)
        combined_tools = coral_tools + agent_tools_for_description
        user_request_tool = "request_question"
        user_answer_tool = "answer_question"
        logger.info(f"Agent tools description: {agent_tools_description}")
    else:
        agent_tools_description = get_tools_description(agent_tools)
        combined_tools = coral_tools + agent_tools
        user_request_tool = "ask_human"
        user_answer_tool = "ask_human"
        logger.info(f"Agent tools description: {agent_tools_description}")

    prompt = ChatPromptTemplate.from_messages([
        (
            "system",
            f"""You are an agent that uses Coral Server tools and agent tools to assist users. **Never terminate the chain.**

            Steps:
            1. Call `list_agents` to get all connected agents and descriptions.
            2. Use `{user_request_tool}` to ask: "How can I assist you today?" and wait for a response.
            3. Think and analyze the user's intent and select relevant agent(s) based on descriptions.
            4. For Coral Server info requests (e.g., list agents), use tools to retrieve and return info, then return to Step 1.
            5. For multi-agent tasks, call `create_thread('threadName': 'user_request', 'participantIds': [IDs, including self])`.
            6. For each selected agent:
               - If not in thread, call `add_participant(threadId=..., 'participantIds': [agent ID])`.
               - Send instruction via `send_message(threadId=..., content="instruction", mentions=[agent ID])`.
               - Use `wait_for_mentions(timeoutMs=60000)` up to 5 times for response.
               - Store response for final answer.
            7. Synthesize responses into a clear "answer".
            8. Respond via `{user_answer_tool}` with the answer or error.
            9. Repeat from Step 1.

            **Never terminate the chain.**

            Coral tools: {coral_tools_description}
            Agent tools: {agent_tools_description}"""
        ),
        ("placeholder", "{agent_scratchpad}")
    ])
    logger.info("Prompt created")

    model = init_chat_model(
        model=os.getenv("MODEL_NAME"),
        model_provider=os.getenv("MODEL_PROVIDER"),
        api_key=os.getenv("API_KEY"),
        temperature=float(os.getenv("MODEL_TEMPERATURE", 0.7)),
        max_tokens=int(os.getenv("MODEL_TOKEN", 2048)),
        base_url=os.getenv("BASE_URL") if os.getenv("BASE_URL") else None
    )

    agent = create_tool_calling_agent(model, combined_tools, prompt)
    return AgentExecutor(agent=agent, tools=combined_tools, verbose=True, return_intermediate_steps=True)

async def main():
    """Main function to run the agent loop."""
    try:
        config = load_config()
        logger.info(f"Configuration loaded: {config['runtime']} mode")

        coral_params = {
            "agentId": config["agent_id"],
            "agentDescription": "An agent that takes user input and interacts with other agents to fulfill requests"
        }
        query_string = urllib.parse.urlencode(coral_params)
        coral_server_url = f"{config['coral_sse_url']}?{query_string}"
        logger.info(f"Connecting to Coral Server: {coral_server_url}")

        client = MultiServerMCPClient(
            connections={
                "coral": {
                    "transport": "sse",
                    "url": coral_server_url,
                    "timeout": 600,
                    "sse_read_timeout": 600,
                }
            }
        )
        logger.info("Coral Server connection established")

        coral_tools = await client.get_tools(server_name="coral")
        logger.info(f"Retrieved {len(coral_tools)} coral tools")

        if config["runtime"] in ("docker", "executable"):
            required_tools = ["request-question", "answer-question"]
            available_tools = [tool.name for tool in coral_tools]
            for tool_name in required_tools:
                if tool_name not in available_tools:
                    error_message = f"Required tool '{tool_name}' not found in coral_tools"
                    logger.error(error_message)
                    raise ValueError(error_message)
            agent_tools = required_tools
        else:
            agent_tools = [
                Tool(
                    name="ask_human",
                    func=None,
                    coroutine=ask_human_tool,
                    description="Ask the user a question and wait for a response."
                )
            ]

        agent_executor = await create_agent(coral_tools, agent_tools, config["runtime"])
        logger.info("Agent executor created")

        iteration_count = 0
        while True:
            iteration_count += 1
            logger.info(f"Starting agent invocation #{iteration_count}")
            try:
                result = await agent_executor.ainvoke({"agent_scratchpad": []})
                await asyncio.sleep(1)
            except Exception as e:
                logger.error(f"Error in agent loop (iteration #{iteration_count}): {str(e)}")
                logger.error(traceback.format_exc())
                await asyncio.sleep(5)
    except Exception as e:
        logger.error(f"Fatal error in main: {str(e)}")
        logger.error(traceback.format_exc())
        raise

if __name__ == "__main__":
    asyncio.run(main())