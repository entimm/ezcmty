from sqlalchemy.dialects.postgresql import TIMESTAMP

UTC_TIMESTAMP = TIMESTAMP(timezone=True, precision=6)
