"""Define the LangGraph agent, its tools, and its reusable instruction skills."""
from __future__ import annotations

import ast
import operator
import os
from typing import Annotated, TypedDict

from langchain_core.messages import BaseMessage, SystemMessage
from langchain_core.tools import tool
from langchain_google_genai import ChatGoogleGenerativeAI
from langgraph.graph import START, StateGraph
from langgraph.graph.message import add_messages
from langgraph.prebuilt import ToolNode, tools_condition

from .knowledge import retrieve_context


class AgentState(TypedDict):
    """State passed between the agent and tool nodes in the graph."""

    messages: Annotated[list[BaseMessage], add_messages]


@tool
def search_knowledge_base(query: str) -> str:
    """Retrieve passages from the user's uploaded documents relevant to a query.

    Args:
        query: A natural-language search query.

    Returns:
        Retrieved passages with source and page information, or a status message.
    """
    return retrieve_context(query)


@tool
def calculator(expression: str) -> str:
    """Evaluate a basic arithmetic expression without executing Python code.

    Args:
        expression: An arithmetic expression containing supported operators.

    Returns:
        The calculated value or a readable error message.
    """
    operations = {
        ast.Add: operator.add,
        ast.Sub: operator.sub,
        ast.Mult: operator.mul,
        ast.Div: operator.truediv,
        ast.Pow: operator.pow,
        ast.USub: operator.neg,
        ast.UAdd: operator.pos,
        ast.Mod: operator.mod,
    }

    def evaluate(node: ast.AST) -> int | float:
        """Evaluate one allowed node from the parsed arithmetic expression."""
        if isinstance(node, ast.Expression):
            return evaluate(node.body)
        if isinstance(node, ast.Constant) and isinstance(node.value, (int, float)):
            return node.value
        if isinstance(node, ast.BinOp) and type(node.op) in operations:
            return operations[type(node.op)](evaluate(node.left), evaluate(node.right))
        if isinstance(node, ast.UnaryOp) and type(node.op) in operations:
            return operations[type(node.op)](evaluate(node.operand))
        raise ValueError("Only basic arithmetic is supported.")

    try:
        return str(evaluate(ast.parse(expression, mode="eval")))
    except Exception as exc:
        return f"Could not calculate that expression: {exc}"


TOOLS = [search_knowledge_base, calculator]

SKILLS = {
    "grounded_answers": (
        "When answering from documents, use retrieved evidence, cite source "
        "filenames, and say when the documents do not contain the answer."
    ),
    "concise": "Be clear and direct. Use a short answer unless the user asks for detail.",
}


def build_agent():
    """Create and compile the LangGraph agent with Gemini and registered tools.

    Returns:
        A compiled graph that accepts conversation messages and returns the
        updated conversation after any tool calls.
    """
    model_name = os.getenv("CHAT_MODEL", "gemini-3.1-flash-lite")
    instructions = (
        "You are a helpful assistant with access to a document knowledge base "
        "and calculator. Give the user a clear answer, but do not reveal private "
        "internal reasoning. Brief activity updates are sent separately by the app. "
        + " ".join(SKILLS.values())
    )
    llm = ChatGoogleGenerativeAI(
        model=model_name,
        google_api_key=os.environ["GOOGLE_API_KEY"],
        temperature=0,
        max_output_tokens=512,
        streaming=True,
    ).bind_tools(TOOLS)

    def assistant(state: AgentState) -> dict[str, list[BaseMessage]]:
        """Invoke Gemini with the system instructions and current messages."""
        messages = [SystemMessage(content=instructions), *state["messages"]]
        return {"messages": [llm.invoke(messages)]}

    graph = StateGraph(AgentState)
    graph.add_node("assistant", assistant)
    graph.add_node("tools", ToolNode(TOOLS))
    graph.add_edge(START, "assistant")
    graph.add_conditional_edges("assistant", tools_condition)
    graph.add_edge("tools", "assistant")
    return graph.compile()
