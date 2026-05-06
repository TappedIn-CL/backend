from datetime import datetime
from sqlalchemy.orm import Session
from app.models.event import Event


def deactivate_past_events(db: Session) -> int:
    """
    Mark events as inactive if their start date has passed.
    Returns the number of events deactivated.
    """
    now = datetime.utcnow()
    past_events = db.query(Event).filter(
        Event.date < now,
        Event.is_active == True
    ).all()
    
    count = 0
    for event in past_events:
        event.is_active = False
        count += 1
    
    if count > 0:
        db.commit()
    
    return count
