# Main entry point for the application
from langgraph.types import Command

from LangCode.agents.supervisor.graph import SupervisorAgent

from LangCode.shared.llm import llm
from LangCode.shared.tools import all_tools


# 当前仅有一个智能体，后续可能会继续完善

def run_with_interrupts(graph, config, initial_state=None):
    """持续处理中断，支持多轮对话"""
    
    events = graph.stream(initial_state or {}, config)
    
    while True:
        interrupted = False
        
        for event in events:
            print("\n事件:", event)
            
            if "__interrupt__" in event:
                # 获取中断信息
                interrupt_info = event["__interrupt__"]
                print(f"\n中断等待输入：")
                print(f"   {interrupt_info[0].value}")
                
                # 等待用户输入
                user_input = input("\n  您的输入: ")
                
                # 恢复执行
                events = graph.stream(Command(resume=user_input), config)
                interrupted = True
                break
        
        if not interrupted:
            print("\n 对话完成！")
            break

if __name__ == "__main__":
    config = {
        "configurable": {
            "thread_id": "customer_service_001"
        }}

    initial_state = {}

    agent = SupervisorAgent(llm=llm, sys_tools=all_tools)
    graph = agent.get_graph()

    run_with_interrupts(graph, config, initial_state)
