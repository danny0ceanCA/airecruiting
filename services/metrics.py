# Placeholder metrics service

def summary(db, school_id):
    """Return metrics for a given school."""
    # In a real implementation, this would query the database.
    return {
        "students": 0,
        "matches": 0,
        "hires_30d": 0,
        "avg_score": 0.0,
    }
