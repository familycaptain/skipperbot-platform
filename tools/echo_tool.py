"""
Echo Tool - Test MCP connectivity
"""


def echo(message: str) -> str:
    """
    Echo back a message - useful for testing MCP connectivity.
    
    Args:
        message: The message to echo back
    """
    try:
        return f"MCP Echo: {message}"
    except Exception as e:
        return f"Error in echo: {str(e)}"
