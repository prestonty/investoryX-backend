from src.trading_engine.services.strategy import Signal

@shared_task(name="trading_engine.execute_signals")
def record_paper_trades():
    pass

def execute_signals():
    pass

def _validate_signal():
    pass

def _build_trade_intent(signal: Signal, price: float, snapshot: PortfolioSnapshot):
    
    pass

def _apply_risk_rules():
    pass

def _estimate_fill_price():
    pass

def _calculate_fee():
    pass

def _size_executable_quantity():
    pass

def _to_trade():
    pass

