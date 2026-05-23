/// ブロック伝播遅延 Δ の適用方式（H: honest、A: 攻撃者 = honest 以外の strategy）。
#[derive(Debug, Clone, Copy, PartialEq, Eq, Default, clap::ValueEnum)]
pub enum PropagationDelayMode {
    /// 全ノード間に同一の遅延 Δ（従来の `--delay` と同じ）。
    #[default]
    Uniform,
    /// 攻撃者有利: H→H, H→A は Δ、A→H, A→A は 0。
    AttackerFavorable,
    /// 攻撃者不利: H→H, H→A は 0、A→H, A→A は Δ。
    AttackerUnfavorable,
}

/// 送信元・受信先の honest 属性とモードから伝播遅延（マイクロ秒）を返す。
pub fn propagation_delay_us(
    mode: PropagationDelayMode,
    delta_us: i64,
    from_honest: bool,
    same_node: bool,
) -> i64 {
    if same_node {
        return 0;
    }
    match mode {
        PropagationDelayMode::Uniform => delta_us,
        PropagationDelayMode::AttackerFavorable => {
            if from_honest {
                delta_us
            } else {
                0
            }
        }
        PropagationDelayMode::AttackerUnfavorable => {
            if from_honest {
                0
            } else {
                delta_us
            }
        }
    }
}

#[cfg(test)]
mod tests {
    use super::*;

    const DELTA: i64 = 600_000;

    #[test]
    fn uniform_applies_delta_to_all_pairs() {
        for (from_h, to_h) in [(true, true), (true, false), (false, true), (false, false)] {
            assert_eq!(
                propagation_delay_us(PropagationDelayMode::Uniform, DELTA, from_h, false),
                DELTA
            );
            let _ = to_h;
        }
    }

    #[test]
    fn attacker_favorable_matrix() {
        assert_eq!(
            propagation_delay_us(PropagationDelayMode::AttackerFavorable, DELTA, true, false),
            DELTA,
            "H→H / H→A"
        );
        assert_eq!(
            propagation_delay_us(PropagationDelayMode::AttackerFavorable, DELTA, false, false),
            0,
            "A→H / A→A"
        );
    }

    #[test]
    fn attacker_unfavorable_matrix() {
        assert_eq!(
            propagation_delay_us(PropagationDelayMode::AttackerUnfavorable, DELTA, true, false),
            0,
            "H→H / H→A"
        );
        assert_eq!(
            propagation_delay_us(PropagationDelayMode::AttackerUnfavorable, DELTA, false, false),
            DELTA,
            "A→H / A→A"
        );
    }

    #[test]
    fn same_node_is_always_zero() {
        for mode in [
            PropagationDelayMode::Uniform,
            PropagationDelayMode::AttackerFavorable,
            PropagationDelayMode::AttackerUnfavorable,
        ] {
            assert_eq!(propagation_delay_us(mode, DELTA, true, true), 0);
            assert_eq!(propagation_delay_us(mode, DELTA, false, true), 0);
        }
    }
}
