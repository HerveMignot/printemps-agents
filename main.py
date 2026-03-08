import sys

AGENTS = {
    "lbc": "scan_classified.agent",
}

if __name__ == "__main__":
    if len(sys.argv) < 2:
        print(f"Usage: python main.py <agent>")
        print(f"Available agents: {', '.join(AGENTS.keys())}")
        sys.exit(1)

    agent_name = sys.argv[1]
    if agent_name not in AGENTS:
        print(f"Unknown agent: {agent_name}")
        print(f"Available agents: {', '.join(AGENTS.keys())}")
        sys.exit(1)

    module = __import__(AGENTS[agent_name], fromlist=["main"])
    module.main()
