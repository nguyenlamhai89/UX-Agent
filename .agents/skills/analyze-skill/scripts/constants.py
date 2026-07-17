"""
constants.py — Category definitions for skill performance analysis.

Defines the 5 criteria categories and their 20 criteria used across
the report formatter, parser, and builder modules.
"""

CATEGORIES = [
    {
        "key": "execution_efficiency",
        "title": "1. ⚡ Execution Efficiency",
        "criteria": [
            ("execution_time", "Execution Time"),
            ("api_call_count", "API Call Count"),
            ("token_usage", "Token Usage"),
            ("resource_consumption", "Resource Consumption"),
        ],
    },
    {
        "key": "output_quality",
        "title": "2. 🎯 Output Quality & Accuracy",
        "criteria": [
            ("output_completeness", "Output Completeness"),
            ("format_compliance", "Format Compliance"),
            ("content_accuracy", "Content Accuracy"),
            ("human_approval_rate", "Human Approval Rate"),
        ],
    },
    {
        "key": "workflow_fit",
        "title": "3. 🔗 Workflow Fit",
        "criteria": [
            ("io_contract_adherence", "I/O Contract Adherence"),
            ("skip_logic_compatibility", "Skip-Logic Compatibility"),
            ("pipeline_passthrough_rate", "Pipeline Passthrough Rate"),
            ("idempotency", "Idempotency"),
        ],
    },
    {
        "key": "reliability",
        "title": "4. 🛡️ Reliability & Error Handling",
        "criteria": [
            ("error_rate", "Error Rate"),
            ("error_recoverability", "Error Recoverability"),
            ("retry_success_rate", "Retry Success Rate"),
            ("known_bug_recurrence", "Known Bug Recurrence"),
        ],
    },
    {
        "key": "cost_scalability",
        "title": "5. 💰 Cost & Scalability",
        "criteria": [
            ("cost_per_execution", "Cost per Execution"),
            ("scaling_behavior", "Scaling Behavior"),
            ("unit_test_coverage", "Unit Test Coverage & Pass Rate"),
        ],
    },
]

# Default value for missing criteria data
DEFAULT_CRITERIA = {
    "score": "N/A",
    "analysis": "No data available.",
    "solutions": [],
}
