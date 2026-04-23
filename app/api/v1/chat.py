"""
对话API
处理用户对话请求，调用Agent执行
"""

from fastapi import APIRouter, Depends, BackgroundTasks
from fastapi.responses import StreamingResponse

from app.core.config import get_settings, Settings
from app.core.exceptions import AgentExecutionException
from app.models.chat import ChatRequest, ChatResponse, ChatHistoryResponse
from agent.graph import run_agent


router = APIRouter(prefix="/chat", tags=["对话"])


@router.post("/send", response_model=ChatResponse)
async def send_message(
    request: ChatRequest,
    background_tasks: BackgroundTasks,
    settings: Settings = Depends(get_settings)
) -> ChatResponse:
    """
    发送对话消息
    
    调用Agent处理用户消息，返回回复。
    如果需要人工审核，返回review_id供后续查询。
    
    流程：
    1. 接收用户消息
    2. 创建或恢复Agent状态
    3. 执行LangGraph
    4. 检查是否需要人工审核
    5. 返回响应或审核标记
    """
    try:
        # 执行Agent
        result = await run_agent(
            session_id=request.session_id,
            user_query=request.message
        )
        
        # TODO: 检查是否需要人工审核
        # 从result中获取interrupt_info判断
        requires_review = False  # 占位
        review_id = None
        
        return ChatResponse(
            session_id=request.session_id,
            response=result.get("final_response", ""),
            requires_review=requires_review,
            review_id=review_id,
            sources=result.get("metadata", {}).get("sources"),
            metadata={
                "execution_time_ms": 0,  # TODO: 真实耗时
                "confidence": result.get("metadata", {}).get("confidence")
            }
        )
        
    except Exception as e:
        raise AgentExecutionException(str(e))


@router.get("/history/{session_id}", response_model=ChatHistoryResponse)
async def get_chat_history(
    session_id: str,
    settings: Settings = Depends(get_settings)
) -> ChatHistoryResponse:
    """
    获取对话历史
    
    返回指定会话的完整对话记录
    """
    # TODO: 从checkpointer或数据库读取对话历史
    # TODO: 检查session_id是否存在
    
    return ChatHistoryResponse(
        session_id=session_id,
        messages=[],
        total=0
    )


@router.post("/stream")
async def stream_chat(
    request: ChatRequest,
    settings: Settings = Depends(get_settings)
):
    """
    流式对话（SSE）
    
    实时返回Agent思考过程和最终回复
    
    TODO: 实现真正的流式输出
    """
    async def event_generator():
        # 模拟流式输出
        yield "data: 思考中...\n\n"
        yield "data: 查询知识库...\n\n"
        yield "data: 生成回复...\n\n"
        yield "data: 完成\n\n"
    
    return StreamingResponse(
        event_generator(),
        media_type="text/event-stream"
    )


# TODO: 未来扩展
# - 添加会话创建API
# - 添加会话结束/归档API
# - 添加消息反馈API（点赞/点踩）
