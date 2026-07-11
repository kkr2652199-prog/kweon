-- 4군 백테·예측 누적 초기화 (lotto_draws 유지)
DELETE FROM lotto_predictions_army4;
DELETE FROM lotto_fullbacktest_army4;
DELETE FROM lotto_evolution_trust_army4;

UPDATE lotto_brain_weights_army4
SET total_predictions = 0,
    total_matches = 0,
    recent_avg_match = 0,
    last_updated_draw = 0;
