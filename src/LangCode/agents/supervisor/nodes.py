from typing import List, Dict, Any, Optional, Iterator, AsyncIterator
from langchain_openai import ChatOpenAI
from langgraph.graph import StateGraph
from LangCode.shared.state import LCState


def call_llm(state: LCState, llm: ChatOpenAI) -> LCState:
