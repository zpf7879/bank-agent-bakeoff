-- Side A system of record: Aurora PostgreSQL
CREATE TABLE IF NOT EXISTS customers (
  customer_id     text PRIMARY KEY,
  name            text NOT NULL,
  customer_since  date NOT NULL,
  segment         text,
  email           text,
  mailing_address text
);

CREATE TABLE IF NOT EXISTS accounts (
  account_id        text PRIMARY KEY,
  customer_id       text NOT NULL REFERENCES customers(customer_id),
  product           text,
  card_last4        text,
  status            text NOT NULL DEFAULT 'active',   -- active | frozen
  hold_reason       text,                             -- internal only
  credit_limit_sgd  numeric(12,2),
  balance_sgd       numeric(12,2),
  overdue_sgd       numeric(12,2) DEFAULT 0,
  late_fee_sgd      numeric(12,2) DEFAULT 0,
  late_fee_date     date,
  last_payment_date date,
  updated_at        timestamptz DEFAULT now()
);

CREATE TABLE IF NOT EXISTS fee_waivers (
  id          bigserial PRIMARY KEY,
  customer_id text NOT NULL REFERENCES customers(customer_id),
  amount_sgd  numeric(12,2),
  reason_code text,
  waived_on   date NOT NULL
);

CREATE TABLE IF NOT EXISTS limit_requests (
  id                  bigserial PRIMARY KEY,
  customer_id         text NOT NULL REFERENCES customers(customer_id),
  requested_limit_sgd numeric(12,2),
  status              text,
  created_at          timestamptz DEFAULT now()
);

CREATE TABLE IF NOT EXISTS disputes (
  dispute_id             text PRIMARY KEY,
  customer_id            text NOT NULL REFERENCES customers(customer_id),
  merchant               text,
  amount_sgd             numeric(12,2),
  opened                 date,
  status                 text,
  provisional_credit_sgd numeric(12,2)
);
