-- datahaus warehouse schema
-- Phase 1: curated layer only (raw and staging added in Phase 2)

CREATE SCHEMA IF NOT EXISTS curated;

CREATE TABLE IF NOT EXISTS curated.btc_ohlcv (
    open_time       BIGINT      NOT NULL,   -- Unix ms timestamp, candle open
    open            DOUBLE      NOT NULL,
    high            DOUBLE      NOT NULL,
    low             DOUBLE      NOT NULL,
    close           DOUBLE      NOT NULL,
    volume          DOUBLE      NOT NULL,   -- Base asset volume
    close_time      BIGINT      NOT NULL,   -- Unix ms timestamp, candle close
    quote_volume    DOUBLE      NOT NULL,   -- Quote asset volume
    trade_count     INTEGER     NOT NULL,
    taker_buy_base_volume   DOUBLE NOT NULL,
    taker_buy_quote_volume  DOUBLE NOT NULL,
    ingested_at     TIMESTAMP   NOT NULL,   -- When this row was ingested (UTC)
    PRIMARY KEY (open_time)
);
