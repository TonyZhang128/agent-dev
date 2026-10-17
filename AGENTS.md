# Project-local skills

The following skills are installed for this project only. Before a matching
development task, read the relevant `SKILL.md` and follow its workflow. Resolve
supporting references relative to that skill's directory.

- LangChain agents, tools, and structured output: `skills/langchain-fundamentals/SKILL.md`
- LangChain package setup, versions, and dependencies: `skills/langchain-dependencies/SKILL.md`
- Retrieval-augmented generation and knowledge bases: `skills/langchain-rag/SKILL.md`
- LangGraph state, nodes, edges, and workflows: `skills/langgraph-fundamentals/SKILL.md`

Source: https://github.com/langchain-ai/langchain-skills
Revision: `16a992f09ab3ccfb642dd4f08d350d833d1990bf`

The `skills/` location is intentional: this environment protects `.agents/`
and `.codex/` from writes. This index provides project instructions for loading
the skills; they are not registered in the default auto-discovery directory.
