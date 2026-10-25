"""Explicitly configured, token-safe Python Humanizer rules."""

from __future__ import annotations

from io import StringIO
import ast
import keyword
import tokenize


def rename_python_identifier(source: str, *, old: str, new: str) -> str:
    """Rename Python NAME tokens only; strings, comments, and literals are untouched."""
    if not old.isidentifier() or keyword.iskeyword(old):
        raise ValueError("old must be a non-keyword Python identifier")
    if not new.isidentifier() or keyword.iskeyword(new):
        raise ValueError("new must be a non-keyword Python identifier")
    try:
        tokens = list(tokenize.generate_tokens(StringIO(source).readline))
    except (IndentationError, tokenize.TokenError) as exc:
        raise ValueError("source is not tokenizable Python") from exc
    replaced = [tokenize.TokenInfo(token.type, new if token.type == tokenize.NAME and token.string == old else token.string, token.start, token.end, token.line) for token in tokens]
    return tokenize.untokenize(replaced)


def rename_python_lambda_parameter(source: str, *, old: str, new: str) -> str:
    """Rename one lambda parameter and its AST-bound references."""
    if not old.isidentifier() or keyword.iskeyword(old):
        raise ValueError("old must be a non-keyword Python identifier")
    if not new.isidentifier() or keyword.iskeyword(new):
        raise ValueError("new must be a non-keyword Python identifier")
    try:
        tree = ast.parse(source)
        tokens = list(tokenize.generate_tokens(StringIO(source).readline))
    except (SyntaxError, IndentationError, tokenize.TokenError) as exc:
        raise ValueError("source is not parseable Python") from exc
    candidates = [
        node for node in ast.walk(tree)
        if isinstance(node, ast.Lambda)
        and any(argument.arg == old for argument in node.args.args)
    ]
    if len(candidates) != 1:
        raise ValueError("expected exactly one lambda binding for the old parameter")
    lambda_node = candidates[0]
    parameter = next(argument for argument in lambda_node.args.args if argument.arg == old)
    target_positions = {
        (node.lineno, node.col_offset)
        for node in ast.walk(lambda_node.body)
        if isinstance(node, ast.Name) and node.id == old
    }
    target_positions.add((parameter.lineno, parameter.col_offset))
    replaced = [
        tokenize.TokenInfo(
            token.type,
            new if token.type == tokenize.NAME and token.start in target_positions else token.string,
            token.start,
            token.end,
            token.line,
        )
        for token in tokens
    ]
    return tokenize.untokenize(replaced)
