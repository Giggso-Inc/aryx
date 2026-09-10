"""APScheduler lifecycle: constructor + start/stop."""

from apscheduler.schedulers.asyncio import AsyncIOScheduler
from apscheduler.triggers.interval import IntervalTrigger


class LifecycleMixin:
    """Constructor + start/stop for the underlying AsyncIOScheduler."""

    def __init__(self):
        """Initialize the scheduler"""
        # Configure AsyncIOScheduler to work with FastAPI's event loop
        import asyncio
        try:
            # Try to get the current event loop
            loop = asyncio.get_event_loop()
        except RuntimeError:
            # If no event loop exists, create a new one
            loop = asyncio.new_event_loop()
            asyncio.set_event_loop(loop)

        self.scheduler = AsyncIOScheduler(event_loop=loop)
        self.is_running = False

    def start(self) -> None:
        """Start the scheduler"""
        if not self.is_running:
            # Run every 15 minutes to check all routine intervals
            self.scheduler.add_job(
                self.process_daily_summaries,
                trigger=IntervalTrigger(minutes=15),
                id='daily_summary_emails',
                replace_existing=True,
                max_instances=1
            )
            self.scheduler.start()
            self.is_running = True
            print("✅ Daily summary email scheduler started (runs every 15 minutes)")

            # Log next run time for debugging
            job = self.scheduler.get_job('daily_summary_emails')
            if job:
                print(f"📅 Next scheduled run: {job.next_run_time}")
                print(f"📋 Job ID: {job.id}, Trigger: {job.trigger}")
            else:
                print("⚠️ Warning: Job not found after adding")

    def stop(self) -> None:
        """Stop the scheduler"""
        if self.is_running:
            self.scheduler.shutdown()
            self.is_running = False
            print("⏹️ Daily summary email scheduler stopped")
