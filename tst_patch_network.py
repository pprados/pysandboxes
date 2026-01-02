from fake_tools import Fake_tools
from langgraph_codeagent.sandboxes.guard_socket import Guard_socket, DENY_LOCALHOST

# This line sets default rules when the module is imported.
# Tests will override this using reset_guard_socket_rules().
Guard_socket.set_rules(DENY_LOCALHOST)

fake_tools = Fake_tools()
fake_tools.load_socket()
