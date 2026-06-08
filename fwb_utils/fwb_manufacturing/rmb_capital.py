# Copyright (c) 2026, WenZhou Furui Handicraft Co.,Ltd. and Contributors
# See license.txt
"""人民币金额中文大写（元/角/分），用于工资单 total_in_words。

ERPNext 原生 `money_in_words` 不支持中文数字大写，会退化成英文
（如 `CNY Five Thousand, Six Hundred And Fifty Three 仅。`）。本模块按
净支付精确额（到角分）输出如「伍仟陆佰伍拾叁元叁角叁分」（不含「人民币」前缀），由
Salary Slip validate 钩子 `set_rmb_total_in_words` 写回 total_in_words /
base_total_in_words。**不碰 ERPNext/HRMS 核心、不 monkey-patch**，升级安全。

`rmb_capital` 是纯函数，可沙箱单测（tests/test_rmb_capital.py）。
支持到「亿」级（工资场景足够）；金额按角分四舍五入。
"""
from __future__ import annotations

from frappe.utils import flt

_DIGITS = "零壹贰叁肆伍陆柒捌玖"
_SMALL_UNITS = ["", "拾", "佰", "仟"]
_GROUP_UNITS = ["", "万", "亿", "兆"]  # 每 4 位一组；工资不会超「亿」


def _four(group: int) -> str:
	"""1..9999 → 大写（不含组单位）；前导零不出、中间零合并、尾零不出。"""
	out = ""
	started = False
	zero_pending = False
	for i in (3, 2, 1, 0):
		d = (group // (10 ** i)) % 10
		if d == 0:
			if started:
				zero_pending = True
		else:
			if zero_pending:
				out += "零"
				zero_pending = False
			out += _DIGITS[d] + _SMALL_UNITS[i]
			started = True
	return out


def _integer_part(yuan: int) -> str:
	"""整数元 → 大写（不含「元」字）。组间按需补单个「零」，去尾零。"""
	if yuan <= 0:
		return ""
	groups = []
	while yuan > 0:
		groups.append(yuan % 10000)
		yuan //= 10000
	parts = []
	highest = len(groups) - 1
	for gi in range(highest, -1, -1):
		g = groups[gi]
		if g == 0:
			if parts and parts[-1] != "零":
				parts.append("零")
			continue
		# 低组不足千且非最高组 → 组间补零（如 一万零一）
		if gi != highest and g < 1000 and parts and parts[-1] != "零":
			parts.append("零")
		parts.append(_four(g) + _GROUP_UNITS[gi])
	return "".join(parts).rstrip("零")


def rmb_capital(amount) -> str:
	"""金额 → 人民币中文大写（到角分）。

	例：5653.33 → 伍仟陆佰伍拾叁元叁角叁分；5653 → 伍仟陆佰伍拾叁元整；
	100.05 → 壹佰元零伍分；0 → 零元整。（不含「人民币」前缀）
	"""
	cents = int(round(flt(amount) * 100))
	neg = cents < 0
	cents = abs(cents)
	yuan = cents // 100
	jiao = (cents // 10) % 10
	fen = cents % 10

	if yuan == 0 and jiao == 0 and fen == 0:
		return "零元整"

	int_str = _integer_part(yuan)

	dec = ""
	if jiao == 0 and fen == 0:
		dec = "整"
	else:
		if jiao:
			dec += _DIGITS[jiao] + "角"
		elif yuan:  # 元后直接是分 → 补「零」（如 壹佰元零伍分）
			dec += "零"
		if fen:
			dec += _DIGITS[fen] + "分"

	if yuan:
		body = int_str + "元" + dec
	else:  # 不足一元，只有角/分
		body = dec.lstrip("零")
	return ("负" if neg else "") + body


def set_rmb_total_in_words(doc, method=None):
	"""Salary Slip validate 钩子：把净支付中文大写写回 total_in_words / base_total_in_words。

	口径：按净支付精确额（到角分），与表单「净支付」数字一致。
	doc_events 在控制器 validate 之后运行，覆写 ERPNext 写入的英文 in_words。
	已提交单不跑 validate，需重存/修订才刷新（见 RULES 升级备忘）。
	"""
	net = doc.get("net_pay")
	if net is not None:
		doc.total_in_words = rmb_capital(net)
	base = doc.get("base_net_pay")
	doc.base_total_in_words = rmb_capital(base if base is not None else net)
