"""Pluggable source providers that fetch books from external sources.

Each provider implements the :class:`~bookbot.providers.base.SourceProvider`
protocol and returns a normalized :class:`~bookbot.providers.base.FetchResult`
the catalog can store and the bot can deliver.
"""
