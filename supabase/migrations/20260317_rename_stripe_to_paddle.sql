-- payments 테이블: stripe 컬럼명 → paddle로 변경
ALTER TABLE IF EXISTS payments RENAME COLUMN stripe_session_id TO paddle_transaction_id;
ALTER TABLE IF EXISTS payments RENAME COLUMN stripe_payment_intent TO paddle_subscription_id;
