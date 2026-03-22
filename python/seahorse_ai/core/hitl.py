import asyncio
import logging
import uuid

logger = logging.getLogger(__name__)

class HitlApprovalManager:
    """Manages Human-in-the-Loop approvals for high-stakes actions."""
    
    def __init__(self):
        # Maps approval_id -> tuple(Event, result_dict)
        self.pending_approvals: dict[str, tuple[asyncio.Event, dict]] = {}
        self._notify_callback = None
        
    def register_notifier(self, callback):
        """Register an async callback fn(approval_id, tool_name, kwargs, agent_id)."""
        self._notify_callback = callback
        
    async def request_approval(self, tool_name: str, kwargs: dict, agent_id: str | None = None) -> bool:
        """
        Pauses the current execution task and waits for human approval.
        Sends an event to the message bus or notification system.
        """
        approval_id = str(uuid.uuid4())[:8]
        event = asyncio.Event()
        result_holder = {"approved": False}
        
        self.pending_approvals[approval_id] = (event, result_holder)
        
        logger.warning(
            f"\n\n🚨 [HITL] HIGH RISK ACTION DETECTED 🚨\n"
            f"Tool: {tool_name}\n"
            f"Args: {kwargs}\n"
            f"Approval ID: {approval_id}\n"
            f"Waiting for human approval...\n"
        )
        
        if self._notify_callback:
            # Fire-and-forget notification
            asyncio.create_task(self._notify_callback(approval_id, tool_name, kwargs, agent_id))

        # PAUSE EXECUTION HERE
        await event.wait()
        
        # Resume and cleanup
        del self.pending_approvals[approval_id]
        
        approved = result_holder["approved"]
        if approved:
            logger.info(f"✅ Action {approval_id} APPROVED by human.")
        else:
            logger.info(f"❌ Action {approval_id} REJECTED by human.")
            
        return approved

    def resolve_approval(self, approval_id: str, approved: bool) -> bool:
        """Called by the Telegram bot to respond to a pending request."""
        if approval_id in self.pending_approvals:
            event, result_holder = self.pending_approvals[approval_id]
            result_holder["approved"] = approved
            event.set() # Wakes up the suspended task!
            return True
        return False

# Global singleton
approval_manager = HitlApprovalManager()
