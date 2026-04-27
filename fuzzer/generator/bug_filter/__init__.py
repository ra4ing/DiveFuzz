# Copyright (c) 2024-2025 Institute of Information Engineering, Chinese Academy of Sciences
#
# DiveFuzz is licensed under Mulan PSL v2.
# You can use this software according to the terms and conditions of the Mulan PSL v2.
# You may obtain a copy of Mulan PSL v2 at:
#          http://license.coscl.org.cn/MulanPSL2
#
# THIS SOFTWARE IS PROVIDED ON AN "AS IS" BASIS, WITHOUT WARRANTIES OF ANY KIND,
# EITHER EXPRESS OR IMPLIED, INCLUDING BUT NOT LIMITED TO NON-INFRINGEMENT,
# MERCHANTABILITY OR FIT FOR A PARTICULAR PURPOSE.
#
# See the Mulan PSL v2 for more details.

"""
DiveFuzz Precision Filter Module

Two-phase filtering with runtime state inspection.

Usage:
    from bug_filter import (
        FilterRegistry, FilterResult,
        pre_execution_filter, post_execution_filter
    )

    # Create registry
    registry = FilterRegistry()

    # Add filter using decorator
    @pre_execution_filter(name="my_filter", opcodes=["div"])
    def my_filter(ctx):
        if ctx.get_xpr(1) == 0:
            return FilterResult.reject("Division by zero")
        return FilterResult.accept()

    registry.register(my_filter)
"""

from .context import (
    FilterContext,
    PreExecutionState,
    PostExecutionState,
)

from .base import (
    FilterPhase,
    FilterResult,
    PrecisionFilter,
    PreExecutionFilter,
    PostExecutionFilter,
    FunctionFilter,
    pre_execution_filter,
    post_execution_filter,
    collect_filters_from_caller,
)

from .registry import (
    FilterRegistry,
    create_registry_for_architecture,
)


__all__ = [
    "FilterContext",
    "PreExecutionState",
    "PostExecutionState",
    "FilterPhase",
    "FilterResult",
    "PrecisionFilter",
    "PreExecutionFilter",
    "PostExecutionFilter",
    "FunctionFilter",
    "FilterRegistry",
    "create_registry_for_architecture",
    "pre_execution_filter",
    "post_execution_filter",
    "collect_filters_from_caller",
]
