### FWB Utils

ERPNext/Frappe manufacturing extension for FWB workshop reporting, QC/rework
feedback, material readiness checks, piece/time wage settlement, and related
manufacturing reports.

计件工资单可通过「从报工生成明细」自动带出核定后的跨期回补，沿用原核定单价。
历史无核定时间记录不自动补发；数量上限与生产、工资报表口径见设计文档 §7.5.2。

The canonical business logic notes live in:

- `../../docs/fwb_utils设计逻辑分析.md`

### Installation

You can install this app using the [bench](https://github.com/frappe/bench) CLI:

```bash
cd $PATH_TO_YOUR_BENCH
bench get-app $URL_OF_THIS_REPO --branch develop
bench install-app fwb_utils
```

### Contributing

This app uses `pre-commit` for code formatting and linting. Please [install pre-commit](https://pre-commit.com/#installation) and enable it for this repository:

```bash
cd apps/fwb_utils
pre-commit install
```

Pre-commit is configured to use the following tools for checking and formatting your code:

- ruff
- eslint
- prettier
- pyupgrade

### License

mit
