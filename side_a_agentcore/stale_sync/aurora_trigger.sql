-- Side A, Scene 2: the extra pipeline that keeps AgentCore Memory in step with Aurora.
--
-- Moving parts you now own:
--   1. aws_lambda extension on the Aurora cluster
--   2. An IAM role attached to the Aurora cluster that allows lambda:InvokeFunction
--   3. This trigger
--   4. The Lambda function in handler.py, with its own IAM role for AgentCore Memory
--   5. Retries, dead-letter queue and monitoring for 1-4 (not shown)
--
-- Replace the ARN and region below before running.

CREATE EXTENSION IF NOT EXISTS aws_lambda CASCADE;

CREATE OR REPLACE FUNCTION notify_memory_on_hold() RETURNS trigger AS $$
BEGIN
  IF NEW.status IS DISTINCT FROM OLD.status THEN
    PERFORM aws_lambda.invoke(
      aws_commons.create_lambda_function_arn(
        'arn:aws:lambda:ap-southeast-1:123456789012:function:card-agent-stale-sync',
        'ap-southeast-1'),
      json_build_object('customer_id', NEW.customer_id, 'status', NEW.status)::json,
      'Event'   -- async; failures do not block the account update
    );
  END IF;
  RETURN NEW;
END;
$$ LANGUAGE plpgsql;

DROP TRIGGER IF EXISTS accounts_status_to_memory ON accounts;
CREATE TRIGGER accounts_status_to_memory
  AFTER UPDATE OF status ON accounts
  FOR EACH ROW EXECUTE FUNCTION notify_memory_on_hold();
