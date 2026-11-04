"""LangGraph RAG agent with a small, explicit tool and skill registry."""
from __future__ import annotations

import os
from typing import Annotated, TypedDict

from langchain_core.messages import BaseMessage
from langchain_core.tools import tool
from langchain_google_genai import ChatGoogleGenerativeAI
from langgraph.graph import END, START, StateGraph
from langgraph.graph.message import add_messages
from langgraph.prebuilt import ToolNode, tools_condition

from .knowledge import retrieve_context


class AgentState(TypedDict):
    messages: Annotated[list[BaseMessage], add_messages]


# Tools are the agent's callable capabilities. Add tools here and include them
# in the registry below to make them available to the graph.
@tool
def search_knowledge_base(query: str) -> str:
    """Search the user's uploaded documents for information relevant to query."""
    return retrieve_context(query)


@tool
def calculator(expression: str) -> str:
    """Evaluate a basic arithmetic expression. Only arithmetic characters are allowed."""
    import ast
    import operator

    ops = {ast.Add: operator.add, ast.Sub: operator.sub, ast.Mult: operator.mul,
           ast.Div: operator.truediv, ast.Pow: operator.pow, ast.USub: operator.neg,
           ast.UAdd: operator.pos, ast.Mod: operator.mod}

    def evaluate(node):
        if isinstance(node, ast.Expression):
            return evaluate(node.body)
        if isinstance(node, ast.Constant) and isinstance(node.value, (int, float)):
            return node.value
        if isinstance(node, ast.BinOp) and type(node.op) in ops:
            return ops[type(node.op)](evaluate(node.left), evaluate(node.right))
        if isinstance(node, ast.UnaryOp) and type(node.op) in ops:
            return ops[type(node.op)](evaluate(node.operand))
        raise ValueError("Only basic arithmetic is supported.")

    try:
        return str(evaluate(ast.parse(expression, mode="eval")))
    except Exception as exc:
        return f"Could not calculate that expression: {exc}"


TOOLS = [search_knowledge_base, calculator]

# Skills are reusable instruction modules that shape agent behavior. Extend
# this mapping with domain-specific skills as the project grows.
SKILLS = {
    "grounded_answers": "When answering from documents, use retrieved evidence, cite source filenames, and say when the documents do not contain the answer.",
    "concise": "Be clear and direct. Use a short answer unless the user asks for detail.",
}


def build_agent():
    model_name = os.getenv("CHAT_MODEL", "gemini-3.1-flash-lite")
    instructions = "You are a helpful assistant with access to a document knowledge base and calculator. " + " ".join(SKILLS.values())
    llm = ChatGoogleGenerativeAI(
        model=model_name,
        google_api_key=os.environ["GOOGLE_API_KEY"],
        temperature=0,
        max_output_tokens=512,
        system_instruction=instructions,
    ).bind_tools(TOOLS)

    def assistant(state: AgentState):
        return {"messages": [llm.invoke(state["messages"])]}

    graph = StateGraph(AgentState)
    graph.add_node("assistant", assistant)
    graph.add_node("tools", ToolNode(TOOLS))
    graph.add_edge(START, "assistant")
    graph.add_conditional_edges("assistant", tools_condition)
    graph.add_edge("tools", "assistant")
    return graph.compile()
