SELECT 'discovered_tokens', COUNT(*) FROM discovered_tokens
UNION ALL SELECT 'radar_tokens', COUNT(*) FROM radar_tokens
UNION ALL SELECT 'token_market_snapshots', COUNT(*) FROM token_market_snapshots
UNION ALL SELECT 'paper_wallets', COUNT(*) FROM paper_wallets
UNION ALL SELECT 'paper_positions', COUNT(*) FROM paper_positions
UNION ALL SELECT 'paper_decision_snapshots', COUNT(*) FROM paper_decision_snapshots
UNION ALL SELECT 'paper_decision_outcomes', COUNT(*) FROM paper_decision_outcomes
UNION ALL SELECT 'paper_decision_enrichments', COUNT(*) FROM paper_decision_enrichments
UNION ALL SELECT 'paper_trade_audit', COUNT(*) FROM paper_trade_audit
UNION ALL SELECT 'token_curve_snapshots', COUNT(*) FROM token_curve_snapshots
UNION ALL SELECT 'token_scores', COUNT(*) FROM token_scores
UNION ALL SELECT 'token_score_history', COUNT(*) FROM token_score_history
UNION ALL SELECT 'radar_snapshots', COUNT(*) FROM radar_snapshots;
