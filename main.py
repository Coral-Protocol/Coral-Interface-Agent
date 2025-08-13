import urllib.parse
from dotenv import load_dotenv
import os, json, asyncio, traceback
from langchain.chat_models import init_chat_model
from langchain.prompts import ChatPromptTemplate
from langchain_mcp_adapters.client import MultiServerMCPClient
from langchain.agents import create_tool_calling_agent, AgentExecutor
from langchain.tools import Tool
import logging
import traceback
from utils.coral_config import mcp_resources_details
from utils.prompts import get_tools_description


logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)


async def request_question(question: str) -> str:
    print(f"Agent asks: {question}")
    response = input("Your response: ")
    return response

async def create_agent(coral_tools, agent_tools):
    combined_tools = coral_tools + agent_tools

    prompt = ChatPromptTemplate.from_messages([
        (
            "system",
            """
            You are a helpful assistant responsible for interacting with the user and working with other agents to meet the user's requests. You can interact with other agents using the chat tools.
            
            User interaction is your speciality. You identify as "{agent_id}".
            
            As an user interface agent, only you can interact with the user. Use the request_question tool to get new tasks from the user.
            
            Make sure that all information comes from reliable sources and that all actions are done using the appropriate tools by the appropriate agents. 
            
            Make sure your responses are much more reliable than guesses! You should make sure no agents are guessing too, by suggesting the relevant agents to do each part of a task to the agents you are working with. Do a refresh of the available agents before asking the user for input.
            
            Make sure to put the name of the agent(s) you are talking to in the mentions field of the send message tool.
            
            {coral_prompt_system}
            
            {tool_guidelines}
            
            Here are the guidelines for using the communication tools:
            """
        ),
        ("placeholder", "{agent_scratchpad}")
    ])
    logger.info(f"Prompt created: {prompt}")

    model = init_chat_model(
        model=os.getenv("MODEL_NAME"),
        model_provider=os.getenv("MODEL_PROVIDER"),
        api_key=os.getenv("MODEL_API_KEY"),
        temperature=float(os.getenv("MODEL_TEMPERATURE", 0.0)),
        max_tokens=int(os.getenv("MODEL_MAX_TOKENS", 8000)),
        base_url=os.getenv("MODEL_BASE_URL", None)
    )
    agent = create_tool_calling_agent(model, combined_tools, prompt)
    return AgentExecutor(agent=agent, tools=combined_tools, verbose=True)

async def main():
    runtime = os.getenv("CORAL_ORCHESTRATION_RUNTIME", None)
    if runtime is None:
        load_dotenv()

    base_url = os.getenv("CORAL_SSE_URL")
    agentID = os.getenv("CORAL_AGENT_ID")

    coral_params = {
        "agentId": agentID,
        "agentDescription": "An agent that takes user input and interacts with other agents to fulfill requests"
    }

    query_string = urllib.parse.urlencode(coral_params)

    CORAL_SERVER_URL = f"{base_url}?{query_string}"
    logger.info(f"Connecting to Coral Server: {CORAL_SERVER_URL}")

    timeout = os.getenv("TIMEOUT_MS", 30000)
    client = MultiServerMCPClient(
        connections={
            "coral": {
                "transport": "sse",
                "url": CORAL_SERVER_URL,
                "timeout": timeout,
                "sse_read_timeout": timeout,
            }
        }
    )
    logger.info("Coral Server Connection Established")

    coral_tools = await client.get_tools(server_name="coral")
    logger.info(f"Coral tools count: {len(coral_tools)}")
    
    if runtime is not None:
        custom_tools = ["request-question", "answer-question"]
        available_tools = [tool.name for tool in coral_tools]

        for tool_name in custom_tools:
            if tool_name not in available_tools:
                error_message = f"Required tool '{tool_name}' not found in coral_tools. Please ensure that while adding the agent on Coral Studio, you include the tool from Custom Tools."
                logger.error(error_message)
                raise ValueError(error_message)        
        agent_tools = custom_tools

    else:
        agent_tools = [
            Tool(
                name="request-question",
                func=None,
                coroutine=request_question,
                description="Ask the user a question and wait for a response."
            )
        ]
    
    agent_executor = await create_agent(coral_tools, agent_tools)

    while True:
        try:
            logger.info("Starting new agent invocation")
            resources = await client.get_resources(server_name="coral")
            coral_resources = mcp_resources_details(resources)
            tool_guidelines= get_tools_description(coral_resources)
            await agent_executor.ainvoke({
                "agent_scratchpad": [],
                "agent_id": os.getenv("CORAL_AGENT_ID"),
                "coral_prompt_system": os.getenv("CORAL_PROMPT_SYSTEM", ""),
                "tool_guidelines": tool_guidelines
            })
            logger.info("Completed agent invocation, restarting loop")
            await asyncio.sleep(1)
        except Exception as e:
            logger.error(f"Error in agent loop: {str(e)}")
            logger.error(traceback.format_exc())
            await asyncio.sleep(5)

if __name__ == "__main__":
    asyncio.run(main())