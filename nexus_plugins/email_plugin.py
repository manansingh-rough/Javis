"""
NEXUS AI v4.0 — Reference Plugin: SMTP/IMAP email operations.
Hardware: Intel i3 7th Gen · 12GB RAM · Ollama + Groq API

Extends NEXUS AI with advanced email operations using the email_client tool.
"""

import json
from nexus_plugins.plugin_base import register_plugin
from nexus_tools.tools.t15_email_client import email_client as _email_client


def email_send(to: str, subject: str, body: str, smtp_server: str = "smtp.gmail.com",
               smtp_port: int = 587, username: str = "", password: str = "",
               attachment_paths: list = None) -> str:
    """
    Send an email. Wraps the email_client tool with simplified interface.
    
    Use when: The user wants to send an email.
    """
    return _email_client("send", to=to, subject=subject, body=body,
                         smtp_server=smtp_server, smtp_port=smtp_port,
                         username=username, password=password,
                         attachment_paths=attachment_paths)


def email_read(imap_server: str = "imap.gmail.com", imap_port: int = 993,
               username: str = "", password: str = "", max_emails: int = 10,
               folder: str = "INBOX") -> str:
    """
    Read emails from an IMAP inbox. Wraps the email_client tool.
    
    Use when: The user wants to check their inbox or read recent emails.
    """
    return _email_client("read", imap_server=imap_server, imap_port=imap_port,
                         username=username, password=password,
                         max_emails=max_emails, folder=folder)


def register():
    """Register this plugin with NEXUS AI."""
    return register_plugin(
        name="email-plugin",
        tool_func=email_send,
        version="1.0.0",
        author="NEXUS AI Team",
        description="Send and read emails via SMTP/IMAP",
        tags=["email", "communication", "productivity"],
        needs_network=True,
        needs_filesystem=True,
    )