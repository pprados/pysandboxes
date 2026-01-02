import logging

from langgraph_codeagent.sandboxes.guard_files import activate_guard_files
from langgraph_codeagent.sandboxes.guard_socket import Guard_socket, \
    activate_guard_socket

logger = logging.getLogger(__name__)


def activate():
    activate_guard_socket()
    activate_guard_files()