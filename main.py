import asyncio
import os
import json
import urllib.parse
from typing import List
from dotenv import load_dotenv

from camel.agents import ChatAgent
from camel.models import ModelFactory
from camel.toolkits import FunctionTool
from camel.toolkits import MCPToolkit, HumanToolkit
from camel.toolkits.mcp_toolkit import MCPClient
from camel.utils.mcp_client import ServerConfig
from camel.logger import get_logger

logger = get_logger(__name__)

def get_user_message():
    return "Begin your task cycle by calling list_agents and asking how you can assist."

def get_tool_name(tool: FunctionTool) -> str:
    """Extract tool name from a FunctionTool object."""
    # Use FunctionTool's get_function_name method for consistency
    try:
        return tool.get_function_name()
    except Exception as e:
        logger.warning(f"Failed to get tool name: {e}")
        return str(tool)

async def get_tools_description(tools: List[FunctionTool]) -> str:
    descriptions = []
    for tool in tools:
        tool_name = get_tool_name(tool)
        schema = tool.get_openai_function_schema() or {}
        arg_names = list(schema.get('parameters', {}).get('properties', {}).keys()) if schema else []
        description = tool.get_function_description() or 'No description'
        schema_str = json.dumps(schema, default=str).replace('{', '{{').replace('}', '}}')
        descriptions.append(
            f"Tool: {tool_name}, Args: {arg_names}, Description: {description}, Schema: {schema_str}"
        )
    return "\n".join(descriptions)

async def create_interface_agent(coral_tools: List[FunctionTool], agent_tools: List[FunctionTool], runtime: str = "devmode"):
    coral_tools_description = await get_tools_description(coral_tools)

    if runtime in ["docker", "executable"]:
        # Ensure agent_tools is a list of FunctionTool objects
        agent_tools_for_description = [
            tool for tool in coral_tools if get_tool_name(tool) in ["request-question", "answer-question"]
        ]
        agent_tools_description = await get_tools_description(agent_tools_for_description)
        combined_tools = coral_tools + agent_tools_for_description
        user_request_tool = "request-question"
        user_answer_tool = "answer-question"
        print(agent_tools_description)
    else:
        # For devmode, agent_tools is already a list of FunctionTool objects
        agent_tools_description = await get_tools_description(agent_tools)
        combined_tools = coral_tools + agent_tools
        user_request_tool = "ask_human"
        user_answer_tool = "ask_human"
    
    sys_msg = f"""
    You are an agent interacting with the tools from Coral Server and using your own `{user_request_tool}` and `{user_answer_tool}` tools to communicate with the user. **You MUST NEVER finish the chain**

    Follow these steps in order:
    1. Call `list_agents` to list all connected agents and get their descriptions.
    2. Use tool `{user_request_tool}` to ask: "How can I assist you today?" and wait for the response.
    3. Understand the user's intent and decide which agent(s) are needed based on their descriptions.
    4. If the user requests Coral Server information (e.g., agent status, connection info), use your tools to retrieve and return the information directly to the user, then go back to Step 1.
    5. If fulfilling the request requires multiple agents, then call
    `create_thread ('threadName': , 'participantIds': [ID of all required agents, including yourself])` to create conversation thread.
    6. For each selected agent:
    * **If the required agent is not in the thread, add it by calling `add_participant(threadId=..., 'participantIds': ID of the agent to add)`.**
    * Construct a clear instruction message for the agent.
    * Use **`send_message(threadId=..., content="instruction", mentions=[Receive Agent Id])`.** (NEVER leave `mentions` as empty)
    * Use `wait_for_mentions(timeoutMs=60000)` to receive the agent's response up to 5 times if no message received.
    * Record and store the response for final presentation.
    7. After all required agents have responded, think about the content to ensure you have executed the instruction to the best of your ability and the tools. Make this your response as "answer".
    8. Always respond back to the user by calling `{user_answer_tool}` with the "answer" or error occurred even if you have no answer or error.
    9. Repeat the process from Step 1.
    **You MUST NEVER finish the chain**
    
    These are the list of coral tools: {coral_tools_description}
    These are the list of agent tools: {agent_tools_description}
    """

    model = ModelFactory.create(
        model_platform=os.getenv("MODEL_PROVIDER"),
        model_type=os.getenv("MODEL_NAME"),
        api_key=os.getenv("API_KEY"),
        model_config_dict={"temperature": float(os.getenv("MODEL_TEMPERATURE"))},
    )

    camel_agent = ChatAgent(
        system_message=sys_msg,
        model=model,
        tools=combined_tools,
        token_limit=int(os.getenv("MODEL_TOKEN"))
    )

    return camel_agent

async def main():

    runtime = os.getenv("CORAL_ORCHESTRATION_RUNTIME", "devmode")

    if runtime == "docker" or runtime == "executable":
        base_url = os.getenv("CORAL_SSE_URL")
        agentID = os.getenv("CORAL_AGENT_ID")
    else:
        load_dotenv()
        base_url = os.getenv("CORAL_SSE_URL")
        agentID = os.getenv("CORAL_AGENT_ID")

    coral_params = {
        "agentId": agentID,
        "agentDescription": "An agent that takes the user's input and interacts with other agents to fulfill the request"
    }

    query_string = urllib.parse.urlencode(coral_params)

    CORAL_SERVER_URL = f"{base_url}?{query_string}"
    print(f"Connecting to Coral Server: {CORAL_SERVER_URL}")
    print("Starting MCP client...")
    
    server = MCPClient(
        ServerConfig(
            url=CORAL_SERVER_URL, 
            timeout=3000000.0, 
            sse_read_timeout=3000000.0, 
            terminate_on_close=True, 
            prefer_sse=True
        ), 
        timeout=3000000.0
    )

    mcp_toolkit = MCPToolkit([server])
    human_toolkit = HumanToolkit()

    connected = await mcp_toolkit.connect()
    coral_tools = connected.get_tools()  # List of FunctionTool objects
    human_tools = human_toolkit.get_tools()  # List of FunctionTool objects
    
    runtime = os.getenv("CORAL_ORCHESTRATION_RUNTIME", "devmode")
    
    if runtime in ["docker", "executable"]:
        required_tool_names = ["request-question", "answer-question"]
        # Filter coral_tools to get FunctionTool objects
        agent_tools = [
            tool for tool in coral_tools if get_tool_name(tool) in required_tool_names
        ]
        available_tool_names = [get_tool_name(tool) for tool in agent_tools]

        # Check if all required tools are present
        for tool_name in required_tool_names:
            if tool_name not in available_tool_names:
                error_message = f"Required tool '{tool_name}' not found in coral_tools. Please ensure that while adding the agent on Coral Studio, you include the tool from Custom Tools."
                logger.error(error_message)
                raise ValueError(error_message, available_tool_names, required_tool_names)
    else:
        agent_tools = human_tools  # Already a list of FunctionTool objects

    camel_agent = await create_interface_agent(coral_tools, agent_tools, runtime)

    print(f"Connected to MCP server as {agentID} at {CORAL_SERVER_URL}")
    
    while True:
        try:
            print("Starting new interaction cycle...")
            resp = await camel_agent.astep(get_user_message())
            print(resp)
            msg0 = resp.msgs[0]
            print(msg0.to_dict())
            await asyncio.sleep(10)
        except Exception as e:
            print("Error during cycle:", e)
            await asyncio.sleep(5)

if __name__ == "__main__":
    asyncio.run(main())