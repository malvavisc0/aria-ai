"""Tests for WorkerAgent factory."""

from llama_index.core.tools import FunctionTool

from aria.agents.worker import WorkerAgent, get_worker_agent


def _make_mock_llm():
    """Create an LLM instance that passes pydantic validation."""
    from llama_index.llms.openai_like import OpenAILike

    return OpenAILike(
        api_base="http://localhost:99999/v1",
        api_key="sk-test",
        is_chat_model=True,
        is_function_calling_model=True,
    )


class TestWorkerAgent:
    """Test WorkerAgent class."""

    def test_get_system_prompt_loads_worker_instructions(self):
        """System prompt should load worker.md instructions."""
        prompt = WorkerAgent.get_system_prompt()
        assert "# Worker" in prompt
        assert "not conversational" in prompt

    def test_get_system_prompt_with_output_dir(self):
        """System prompt should include output directory when provided."""
        prompt = WorkerAgent.get_system_prompt(output_dir="/tmp/test_output")
        assert "/tmp/test_output" in prompt
        assert "Output Directory" in prompt

    def test_get_system_prompt_without_output_dir(self):
        """System prompt should not include output dir section when None."""
        prompt = WorkerAgent.get_system_prompt(output_dir=None)
        assert "Output Directory" not in prompt

    def test_get_system_prompt_with_extras(self):
        """System prompt should include extras when provided."""
        prompt = WorkerAgent.get_system_prompt(extras="Extra context here")
        assert "Extra context here" in prompt


class TestGetWorkerAgent:
    """Test get_worker_agent factory."""

    def test_returns_worker_agent_instance(self):
        """Factory should return a WorkerAgent instance."""
        mock_llm = _make_mock_llm()
        agent = get_worker_agent(llm=mock_llm)
        assert isinstance(agent, WorkerAgent)

    def test_agent_name_is_worker(self):
        """Agent name should be 'Worker'."""
        mock_llm = _make_mock_llm()
        agent = get_worker_agent(llm=mock_llm)
        assert agent.name == "Worker"

    def test_agent_has_tools(self):
        """Agent should have tools loaded."""
        mock_llm = _make_mock_llm()
        agent = get_worker_agent(llm=mock_llm)
        assert agent.tools is not None
        assert len(agent.tools) > 0

    def test_agent_has_execution_tools_without_reasoning_or_memory(self):
        """Worker exposes execution tools but no conversation memory."""
        mock_llm = _make_mock_llm()
        agent = get_worker_agent(llm=mock_llm)
        assert agent.tools is not None
        tools = [t for t in agent.tools if isinstance(t, FunctionTool)]
        names = {t.metadata.name for t in tools}
        assert "plan" in names
        assert "scratchpad" in names
        assert "shell" in names
        assert "read_file" in names
        assert "write_file" in names
        assert "reasoning" not in names
        assert "ax" in names

    def test_agent_with_output_dir(self):
        """Agent system prompt should include output dir."""
        mock_llm = _make_mock_llm()
        agent = get_worker_agent(llm=mock_llm, output_dir="/tmp/worker_123")
        assert agent.system_prompt is not None
        assert "/tmp/worker_123" in agent.system_prompt
