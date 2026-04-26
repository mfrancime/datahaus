-- datahaus warehouse schema
-- Phase 2: unified multi-exchange table

CREATE SCHEMA IF NOT EXISTS curated;

CREATE TABLE IF NOT EXISTS curated.btc_ohlcv (
    exchange        VARCHAR     NOT NULL,   -- Exchange identifier (binance, bybit, okx)
    open_time       BIGINT      NOT NULL,   -- Unix ms timestamp, candle open
    open            DOUBLE      NOT NULL,
    high            DOUBLE      NOT NULL,
    low             DOUBLE      NOT NULL,
    close           DOUBLE      NOT NULL,
    volume          DOUBLE      NOT NULL,   -- Base asset volume
    close_time      BIGINT,                 -- Unix ms timestamp, candle close (Binance only)
    quote_volume    DOUBLE,                 -- Quote asset volume (Binance only)
    trade_count     INTEGER,                -- Number of trades (Binance only)
    taker_buy_base_volume   DOUBLE,         -- Taker buy base volume (Binance only)
    taker_buy_quote_volume  DOUBLE,         -- Taker buy quote volume (Binance only)
    confirm         BOOLEAN,                -- Candle confirmed flag (OKX only)
    ingested_at     TIMESTAMP   NOT NULL,   -- When this row was ingested (UTC)
    PRIMARY KEY (exchange, open_time)
);
