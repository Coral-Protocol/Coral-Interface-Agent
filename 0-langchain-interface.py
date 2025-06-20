import asyncio
import os
import json
import logging
import urllib.parse
from dotenv import load_dotenv
from anyio import ClosedResourceError
from langchain_mcp_adapters.client import MultiServerMCPClient
from langchain.prompts import ChatPromptTemplate
from langchain_openai import ChatOpenAI
from langchain.agents import create_tool_calling_agent, AgentExecutor
from langchain.tools import Tool
from langchain_community.callbacks import get_openai_callback

logging.basicConfig(level=logging.INFO, format='%(asctime)s - %(levelname)s - %(message)s')
logger = logging.getLogger(__name__)

load_dotenv()

base_url = os.getenv("CORAL_SSE_URL")
agentID = os.getenv("CORAL_AGENT_ID")

params = {
    # "waitForAgents": 1,
    "agentId": agentID,
    "agentDescription": "An agent that takes the user's input and interacts with other agents to fulfill the request",
}

query_string = urllib.parse.urlencode(params)
MCP_SERVER_URL = f"{base_url}?{query_string}"
AGENT_NAME = "user_interaction_agent"

def get_tools_description(tools):
    return "\n".join(
        f"Tool: {tool.name}, Schema: {json.dumps(tool.args).replace('{', '{{').replace('}', '}}')}"
        for tool in tools
    )

async def ask_human_tool(question: str) -> str:
    print(f"Agent asks: {question}")
    runtime = os.getenv("CORAL_ORCHESTRATION_RUNTIME", "devmode")
    
    if runtime == "docker":
        load_dotenv(override=True)
        response = os.getenv("HUMAN_RESPONSE")
        if response is None:
            logger.error("No HUMAN_RESPONSE coming from Coral Server Orchestrator")
    else:
        response = input("Your response: ")
    
    return response
    
async def create_interface_agent(client, tools):
    tools_description = get_tools_description(tools)
    
    prompt = ChatPromptTemplate.from_messages([
        (
            "system",
            f"""You are an agent interacting with the tools from Coral Server and using your own `ask_human` tool to communicate with the user,**You MUST NEVER finish the chain**

            Follow these steps in order:

            1. Use `list_agents` to list all connected agents and get their descriptions.
            2. Use `ask_human` to ask: "How can I assist you today?" and wait for the response.
            3. Understand the user's intent and decide which agent(s) are needed based on their descriptions.
            4. If the user requests Coral Server information (e.g., agent status, connection info), use your tools to retrieve and return the information directly to the user, then go back to Step 1.
            5. If fulfilling the request requires multiple agents, determine the sequence and logic for calling them.
            6. For each selected agent:
            * **If a conversation thread with the agent does not exist, use `create_thread` to create one.**
            * Construct a clear instruction message for the agent.
            * Use **`send_message(senderId=..., mentions=[Receive Agent Id], threadId=..., content="instruction")`.**
            * Use `wait_for_mentions(timeoutMs=60000)` to receive the agent's response up to 5 times if no message received.
            * Record and store the response for final presentation.
            7. After all required agents have responded, show the complete conversation (all thread messages) to the user.
            8. Call `ask_human` to ask: "Is there anything else I can help you with?"
            9. Repeat the process from Step 1.
            
            - Use only tools: {tools_description}"""),
        ("placeholder", "{agent_scratchpad}")
    ])

    model = ChatOpenAI(
        model="gpt-4.1-mini-2025-04-14",
        api_key=os.getenv("OPENAI_API_KEY"),
        temperature=0.3,
        max_tokens=32768
    )

    '''model = ChatGroq(
        model="llama-3.3-70b-versatile",
        temperature=0.3
    )'''

    agent = create_tool_calling_agent(model, tools, prompt)
    return AgentExecutor(agent=agent, tools=tools, max_iterations=None ,verbose=True, stream_runnable=False)

async def main():
    max_retries = 5
    retry_delay = 5  # seconds

    for attempt in range(max_retries):
        client = None
        try:
            client = MultiServerMCPClient(
                connections={
                    "coral": {
                        "transport": "sse",
                        "url": MCP_SERVER_URL,
                        "timeout": 600,
                        "sse_read_timeout": 600,
                    }
                }
            )
            logger.info(f"Initialized MultiServerMCPClient to {MCP_SERVER_URL}")

            tools = await client.get_tools()

            tools.append(
                Tool(
                    name="ask_human",
                    func=None,
                    coroutine=ask_human_tool,
                    description="Ask the user a question and wait for a response."
                )
            )
            logger.info(f"Tools Description:\n{get_tools_description(tools)}")

            # with get_openai_callback() as cb:
            agent_executor = await create_interface_agent(client, tools)
            await agent_executor.ainvoke({})
                # logger.info("Token usage:")
                # logger.info(f"  Prompt Tokens: {cb.prompt_tokens}")
                # logger.info(f"  Completion Tokens: {cb.completion_tokens}")
                # logger.info(f"  Total Tokens: {cb.total_tokens}")
                # logger.info(f"  Total Cost (USD): ${cb.total_cost:.6f}")


        except ClosedResourceError as e:
            logger.error(f"ClosedResourceError on attempt {attempt + 1}: {e}")
            if attempt < max_retries - 1:
                logger.info(f"Retrying in {retry_delay} seconds...")
                await asyncio.sleep(retry_delay)
                continue
            else:
                logger.error("Max retries reached. Exiting.")
                raise

        except Exception as e:
            logger.error(f"Unexpected error on attempt {attempt + 1}: {e}")
            if attempt < max_retries - 1:
                logger.info(f"Retrying in {retry_delay} seconds...")
                await asyncio.sleep(retry_delay)
                continue
            else:
                logger.error("Max retries reached. Exiting.")
                raise

if __name__ == "__main__":
    asyncio.run(main())

