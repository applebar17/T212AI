"""External data-source integrations.

Import concrete providers from their own packages, for example:

- `t212ai.data_sources.alpha_vantage`
- `t212ai.data_sources.eodhd`
- `t212ai.data_sources.yahoo`

The package root intentionally stays lightweight to avoid import cycles between
provider-specific toolboxes and the generic GenAI tool registry.
"""
