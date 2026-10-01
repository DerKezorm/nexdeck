"""The energy flow of evcc: where the power goes, from either shape evcc answers in."""

from __future__ import annotations

from app.adapters import get_adapter
from app.adapters.evcc import flow_of


def test_the_flow_carries_every_place_in_kilowatts_with_evccs_signs() -> None:
    state = {
        "pvPower": 5100, "homePower": 600, "grid": {"power": -1200},
        "batteryPower": -2100, "batterySoc": 64,
        "loadpoints": [{"chargePower": 7400}, {"chargePower": 0}],
    }
    flow = flow_of(state).meta["flow"]
    assert flow == {"solar": 5.1, "home": 0.6, "grid": -1.2, "battery": -2.1, "battery_soc": 64.0, "car": 7.4}


def test_a_house_without_battery_or_wallbox_leaves_them_out() -> None:
    flow = flow_of({"pvPower": 0, "homePower": 450, "gridPower": 450}).meta["flow"]
    assert flow["battery"] is None and flow["battery_soc"] is None and flow["car"] is None
    assert flow["grid"] == 0.45, "the older top-level gridPower is read as well"


def test_several_batteries_add_up() -> None:
    flow = flow_of({"homePower": 1000, "battery": [{"power": 500, "soc": 40}, {"power": 300, "soc": 60}], "loadpoints": []}).meta["flow"]
    assert flow["battery"] == 0.8 and flow["battery_soc"] == 50.0


def test_the_demo_balances() -> None:
    flow = get_adapter("evcc").demo("flow", {}, 17).meta["flow"]
    taken = flow["solar"] + flow["grid"] + flow["battery"]
    used = flow["home"] + flow["car"]
    assert abs(taken - used) < 0.05, "what comes in is what goes out"
