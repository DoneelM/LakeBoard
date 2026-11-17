-- Messages per sender (user = guest or host, agent = support) and labelled tone. The sample spells a few tones two
-- ways ("aggreeable"); they are counted as written.
SELECT
  m.sender,
  LOWER(m.sentiment) AS tone,
  COUNT(*)           AS messages
FROM samples.wanderbricks.customer_support_logs AS s
LATERAL VIEW EXPLODE(s.messages) AS m
GROUP BY m.sender, LOWER(m.sentiment)
ORDER BY messages DESC
