"""Role-filtered read models; no database or HTTP coupling."""

from .history import no_cost


def public_state(state, costs_allowed, today, config):
    p, s, g = state["p"], state["s"], state["g"]
    if not costs_allowed:
        p = [no_cost(x) for x in p]
        s = [dict(x, l=[no_cost(l) for l in x.get("l", [])]) for x in s]
        # Historical cost-change audit rows must not leak through the general state API.
        g = [x for x in g if "cost" not in str(x.get("k", "")).lower()]
    out = {"p": p, "s": s, "g": g, "today": today, "cfg": config}
    if costs_allowed:
        out["purchases"] = state.get("purchases", [])
        out["suppliers"] = state.get("suppliers", [])
    return out


def cashier_state(products, costs_allowed, today):
    """The cashier poll needs catalog/stock only, never sales or audit history."""
    products = products if costs_allowed else [no_cost(p) for p in products]
    return {"p": products, "today": today}


def current_sales_state(sales, costs_allowed, day):
    """Live Sales needs today's transactions, not the whole catalog and history."""
    sales = [s for s in sales if s.get("d") == day]
    if not costs_allowed:
        sales = [dict(s, l=[no_cost(line) for line in s.get("l", [])]) for s in sales]
    return {"s": sales, "today": day}


