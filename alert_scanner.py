#!/usr/bin/env python3
"""
Alert Scanner - Runs periodically and outputs signals for OpenClaw to relay.
Designed to be called from OpenClaw cron with output sent to Telegram.
"""
import json
import sys
from datetime import datetime
from scanner import scan_all, Signal

MIN_EDGE_ALERT = 0.15  # Only alert on 15%+ edges
MAX_ALERTS = 5  # Max alerts per scan


def format_alert(signals: list[Signal]) -> str:
    """Format signals for Telegram alert."""
    if not signals:
        return ""
    
    lines = [f"🌡️ **{len(signals)} Weather Signal{'s' if len(signals) > 1 else ''}** ({datetime.now().strftime('%H:%M')})\n"]
    
    for s in signals[:MAX_ALERTS]:
        emoji = "📈" if s.direction == "YES" else "📉"
        price_cents = s.market_price * 100
        payout = s.suggested_contracts * 1.0
        profit = payout - s.suggested_risk
        lines.append(f"{emoji} **{s.city}** {s.target_date[-5:]}")
        lines.append(f"   `{s.ticker}`")
        lines.append(f"   {s.direction} @ {price_cents:.0f}¢ → Model: {s.model_prob:.0%}")
        lines.append(f"   **Edge: {s.edge*100:.1f}%** | {s.suggested_contracts} contracts")
        lines.append(f"   Risk ${s.suggested_risk:.2f} → Win +${profit:.2f}")
        lines.append("")
    
    if len(signals) > MAX_ALERTS:
        lines.append(f"_+{len(signals) - MAX_ALERTS} more signals..._")
    
    return "\n".join(lines)


def main():
    """Run scan and output alert if signals found."""
    # Suppress scanner output
    import io
    from contextlib import redirect_stdout
    
    f = io.StringIO()
    with redirect_stdout(f):
        signals = scan_all()
    
    # Filter to high-edge signals only
    high_edge = [s for s in signals if s.edge >= MIN_EDGE_ALERT and s.suggested_size > 0]
    
    if high_edge:
        alert = format_alert(high_edge)
        print(alert)
        return 0
    else:
        # No signals worth alerting
        return 0


if __name__ == "__main__":
    sys.exit(main())
