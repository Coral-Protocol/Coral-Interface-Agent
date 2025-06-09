## [Interface Agent](https://github.com/Coral-Protocol/Coral-Interface-Agent)

User Interaction Agent is the main interface for receiving user instructions, coordinating multi-agent tasks, and logging conversations via the terminal.

## Responsibility

**User Interaction Agent** acts as the main interface for coordinating user instructions and managing multi-agent tasks. It interacts with the user via terminal and orchestrates requests among various agents, ensuring seamless workflow and conversation logging.


## Details
- **Framework**: LangChain
- **Tools used**: Coral MCP Tools, ask_human Tool (human-in-the-loop)
- **AI model**: GPT-4o
- **Date added**: June 4, 2025
- **License**: MIT 

## Clone & Install Dependencies

1. Run [Coral Server](https://github.com/Coral-Protocol/coral-server)
<details>

This agent runs on Coral Server, follow the instrcutions below to run the server. In a new terminal clone the repository:


```bash
git clone https://github.com/Coral-Protocol/coral-server.git
```

Navigate to the project directory:
```bash
cd coral-server
```
Run the server
```bash
./gradlew run
```
</details>

2. Agent Installation
<details>

In a new terminal clone the repository
```bash
git clone https://github.com/Coral-Protocol/Coral-Interface-Agent.git
```
Navigate to the project directory:
```bash
cd Coral-Interface-Agent
```

Install `uv`:
```bash
pip install uv
```
Install dependencies from `pyproject.toml` using `uv`:
```bash
uv sync
```

</details>

## Configure Environment Variables
Get the API Key:
[OpenAI](https://platform.openai.com/api-keys)


Create .env file in project root
```bash
cp -r .env_sample .env
```

## Run Agent
Run the agent using `uv`:
```bash
uv run python 0-langchain-interface.py
```

## Example Output

```text
Agent: How can I assist you today?
```

## Creator Details
- **Name**: Suman Deb
- **Affiliation**: Coral Protocol
- **Contact**: [Discord](https://discord.com/invite/Xjm892dtt3)
