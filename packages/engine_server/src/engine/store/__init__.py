"""Job records and result artifacts.

Redis holds job status and idempotency; Parquet holds result series. Neither is
the durable financial record -- that belongs to api-control (spec section 9.4).
"""
