// 错误日志页面JavaScript (Updated for new structure, no Bootstrap)

// 页面滚动功能
function scrollToTop() {
  window.scrollTo({ top: 0, behavior: "smooth" });
}

function scrollToBottom() {
  window.scrollTo({ top: document.body.scrollHeight, behavior: "smooth" });
}

// API 调用辅助函数
async function fetchAPI(url, options = {}) {
  // Ensure GET requests are not cached by the browser
  if (!options.method || options.method.toUpperCase() === 'GET') {
    options.cache = 'no-store';
  }

  try {
    const response = await fetch(url, options);

    // Handle cases where response might be empty but still ok (e.g., 204 No Content for DELETE)
    if (response.status === 204) {
      return null; // Indicate success with no content
    }

    let responseData;
    try {
      responseData = await response.json();
    } catch (e) {
      // Handle non-JSON responses if necessary, or assume error if JSON expected
      if (!response.ok) {
        // If response is not ok and not JSON, use statusText
        throw new Error(
          `HTTP error! status: ${response.status} - ${response.statusText}`
        );
      }
      // If response is ok but not JSON, maybe return raw text or handle differently
      // For now, let's assume successful non-JSON is not expected or handled later
      console.warn("Response was not JSON for URL:", url);
      return await response.text(); // Or handle as needed
    }

    if (!response.ok) {
      // Prefer error message from API response body if available
      const message =
        responseData?.detail ||
        `HTTP error! status: ${response.status} - ${response.statusText}`;
      throw new Error(message);
    }

    return responseData; // Return parsed JSON data for successful responses
  } catch (error) {
    // Catch network errors or errors thrown from above
    console.error(
      "API Call Failed:",
      error.message,
      "URL:",
      url,
      "Options:",
      options
    );
    // Re-throw the error so the calling function knows the operation failed
    throw error;
  }
}

// Refresh function removed as the buttons are gone.
// If refresh functionality is needed elsewhere, it can be triggered directly by calling loadErrorLogs().

// 全局状态管理
let errorLogState = {
  currentPage: 1,
  pageSize: 10,
  logs: [], // 存储获取的日志
  sort: {
    field: "id", // 默认按 ID 排序
    order: "desc", // 默认降序
  },
  search: {
    key: "",
    error: "",
    errorCode: "",
    startDate: "",
    endDate: "",
  },
};

// DOM Elements Cache
let pageSizeSelector;
// let refreshBtn; // Removed, as the button is deleted
let tableBody;
let paginationElement;
let loadingIndicator;
let noDataMessage;
let errorMessage;
let logDetailModal;
let modalCloseBtns; // Collection of close buttons for the modal
let keySearchInput;
let errorSearchInput;
let errorCodeSearchInput; // Added error code input
let startDateInput;
let endDateInput;
let searchBtn;
let pageInput;
let goToPageBtn;
let selectAllCheckbox; // 新增：全选复选框
let copySelectedKeysBtn; // 新增：复制选中按钮
let deleteSelectedBtn; // 新增：批量删除按钮
let sortByIdHeader; // 新增：ID 排序表头
let sortIcon; // 新增：排序图标
let selectedCountSpan; // 新增：选中计数显示
let deleteConfirmModal; // 新增：删除确认模态框
let closeDeleteConfirmModalBtn; // 新增：关闭删除模态框按钮
let cancelDeleteBtn; // 新增：取消删除按钮
let confirmDeleteBtn; // 新增：确认删除按钮
let deleteConfirmMessage; // 新增：删除确认消息元素
let idsToDeleteGlobally = []; // 新增：存储待删除的ID
let currentConfirmCallback = null; // 新增：存储当前的确认回调
let deleteAllLogsBtn; // 新增：清空全部按钮

// Helper functions for initialization
function cacheDOMElements() {
  pageSizeSelector = document.getElementById("pageSize");
  tableBody = document.getElementById("errorLogsTable");
  paginationElement = document.getElementById("pagination");
  loadingIndicator = document.getElementById("loadingIndicator");
  noDataMessage = document.getElementById("noDataMessage");
  errorMessage = document.getElementById("errorMessage");
  logDetailModal = document.getElementById("logDetailModal");
  modalCloseBtns = document.querySelectorAll(
    "#closeLogDetailModalBtn, #closeModalFooterBtn"
  );
  keySearchInput = document.getElementById("keySearch");
  errorSearchInput = document.getElementById("errorSearch");
  errorCodeSearchInput = document.getElementById("errorCodeSearch");
  startDateInput = document.getElementById("startDate");
  endDateInput = document.getElementById("endDate");
  searchBtn = document.getElementById("searchBtn");
  pageInput = document.getElementById("pageInput");
  goToPageBtn = document.getElementById("goToPageBtn");
  selectAllCheckbox = document.getElementById("selectAllCheckbox");
  copySelectedKeysBtn = document.getElementById("copySelectedKeysBtn");
  deleteSelectedBtn = document.getElementById("deleteSelectedBtn");
  sortByIdHeader = document.getElementById("sortById");
  if (sortByIdHeader) {
    sortIcon = sortByIdHeader.querySelector("i");
  }
  selectedCountSpan = document.getElementById("selectedCount");
  deleteConfirmModal = document.getElementById("deleteConfirmModal");
  closeDeleteConfirmModalBtn = document.getElementById(
    "closeDeleteConfirmModalBtn"
  );
  cancelDeleteBtn = document.getElementById("cancelDeleteBtn");
  confirmDeleteBtn = document.getElementById("confirmDeleteBtn");
  deleteConfirmMessage = document.getElementById("deleteConfirmMessage");
  deleteAllLogsBtn = document.getElementById("deleteAllLogsBtn"); // 缓存清空全部按钮
 }
  
 function initializePageSizeControls() {
  if (pageSizeSelector) {
    pageSizeSelector.value = errorLogState.pageSize;
    pageSizeSelector.addEventListener("change", function () {
      errorLogState.pageSize = parseInt(this.value);
      errorLogState.currentPage = 1; // Reset to first page
      loadErrorLogs();
    });
  }
}

function initializeSearchControls() {
  if (searchBtn) {
    searchBtn.addEventListener("click", function () {
      errorLogState.search.key = keySearchInput
        ? keySearchInput.value.trim()
        : "";
      errorLogState.search.error = errorSearchInput
        ? errorSearchInput.value.trim()
        : "";
      errorLogState.search.errorCode = errorCodeSearchInput
        ? errorCodeSearchInput.value.trim()
        : "";
      errorLogState.search.startDate = startDateInput
        ? startDateInput.value
        : "";
      errorLogState.search.endDate = endDateInput ? endDateInput.value : "";
      errorLogState.currentPage = 1; // Reset to first page on new search
      loadErrorLogs();
    });
  }
}

function initializeModalControls() {
  // Log Detail Modal
  if (logDetailModal && modalCloseBtns) {
    modalCloseBtns.forEach((btn) => {
      btn.addEventListener("click", closeLogDetailModal);
    });
    logDetailModal.addEventListener("click", function (event) {
      if (event.target === logDetailModal) {
        closeLogDetailModal();
      }
    });
  }

  // Delete Confirm Modal
  if (closeDeleteConfirmModalBtn) {
    closeDeleteConfirmModalBtn.addEventListener(
      "click",
      hideDeleteConfirmModal
    );
  }
  if (cancelDeleteBtn) {
    cancelDeleteBtn.addEventListener("click", hideDeleteConfirmModal);
  }
  if (confirmDeleteBtn) {
    confirmDeleteBtn.addEventListener("click", handleConfirmDelete);
  }
  if (deleteConfirmModal) {
    deleteConfirmModal.addEventListener("click", function (event) {
      if (event.target === deleteConfirmModal) {
        hideDeleteConfirmModal();
      }
    });
  }
}

function initializePaginationJumpControls() {
  if (goToPageBtn && pageInput) {
    goToPageBtn.addEventListener("click", function () {
      const targetPage = parseInt(pageInput.value);
      if (!isNaN(targetPage) && targetPage >= 1) {
        errorLogState.currentPage = targetPage;
        loadErrorLogs();
        pageInput.value = "";
      } else {
        showNotification("请输入有效的页码", "error", 2000);
        pageInput.value = "";
      }
    });
    pageInput.addEventListener("keypress", function (event) {
      if (event.key === "Enter") {
        goToPageBtn.click();
      }
    });
  }
}

function initializeActionControls() {
  if (deleteSelectedBtn) {
    deleteSelectedBtn.addEventListener("click", handleDeleteSelected);
  }
  if (sortByIdHeader) {
    sortByIdHeader.addEventListener("click", handleSortById);
  }
  // Bulk selection listeners are closely related to actions
  setupBulkSelectionListeners();
  
   // 为 "清空全部" 按钮添加事件监听器
   if (deleteAllLogsBtn) {
     deleteAllLogsBtn.addEventListener("click", function() {
       const message = "您确定要清空所有错误日志吗？此操作不可恢复！";
       showDeleteConfirmModal(message, handleDeleteAllLogs); // 传入回调
     });
   }
 }
  
 // 新增：处理 "清空全部" 逻辑的函数
 async function handleDeleteAllLogs() {
   const url = "/api/logs/errors/all";
   const options = {
     method: "DELETE",
   };
 
   try {
     await fetchAPI(url, options);
     showNotification("所有错误日志已成功清空", "success");
     if (selectAllCheckbox) selectAllCheckbox.checked = false; // 取消全选
     loadErrorLogs(); // 重新加载日志
   } catch (error) {
     console.error("清空所有错误日志失败:", error);
     showNotification(`清空失败: ${error.message}`, "error", 5000);
   }
 }
  
 // 页面加载完成后执行
document.addEventListener("DOMContentLoaded", function () {
  cacheDOMElements();
  initializePageSizeControls();
  initializeSearchControls();
  initializeModalControls();
  initializePaginationJumpControls();
  initializeActionControls();

  // Initial load of error logs
  loadErrorLogs();

  // Add event listeners for copy buttons inside the modal and table
  // This needs to be called after initial render and potentially after each render if content is dynamic
  setupCopyButtons();
});

// 新增：显示删除确认模态框
function showDeleteConfirmModal(message, confirmCallback) {
  if (deleteConfirmModal && deleteConfirmMessage) {
    deleteConfirmMessage.textContent = message;
    currentConfirmCallback = confirmCallback; // 存储回调
    deleteConfirmModal.classList.add("show");
    document.body.style.overflow = "hidden"; // Prevent body scrolling
  }
}
 
// 新增：隐藏删除确认模态框
function hideDeleteConfirmModal() {
  if (deleteConfirmModal) {
    deleteConfirmModal.classList.remove("show");
    document.body.style.overflow = ""; // Restore body scrolling
    idsToDeleteGlobally = []; // 清空待删除ID
    currentConfirmCallback = null; // 清除回调
  }
}
 
// 新增：处理确认删除按钮点击
function handleConfirmDelete() {
  if (typeof currentConfirmCallback === 'function') {
    currentConfirmCallback(); // 调用存储的回调
  }
  hideDeleteConfirmModal(); // 关闭模态框
}
 
// Fallback copy function using document.execCommand
function fallbackCopyTextToClipboard(text) {
  const textArea = document.createElement("textarea");
  textArea.value = text;

  // Avoid scrolling to bottom
  textArea.style.top = "0";
  textArea.style.left = "0";
  textArea.style.position = "fixed";

  document.body.appendChild(textArea);
  textArea.focus();
  textArea.select();

  let successful = false;
  try {
    successful = document.execCommand("copy");
  } catch (err) {
    console.error("Fallback copy failed:", err);
    successful = false;
  }

  document.body.removeChild(textArea);
  return successful;
}

// Helper function to handle feedback after copy attempt (both modern and fallback)
function handleCopyResult(buttonElement, success) {
  const originalIcon = buttonElement.querySelector("i").className; // Store original icon class
  const iconElement = buttonElement.querySelector("i");
  if (success) {
    iconElement.className = "fas fa-check text-success-500"; // Use checkmark icon class
    showNotification("已复制到剪贴板", "success", 2000);
  } else {
    iconElement.className = "fas fa-times text-danger-500"; // Use error icon class
    showNotification("复制失败", "error", 3000);
  }
  setTimeout(
    () => {
      iconElement.className = originalIcon;
    },
    success ? 2000 : 3000
  ); // Restore original icon class
}

// 新的内部辅助函数，封装实际的复制操作和反馈
function _performCopy(text, buttonElement) {
  let copySuccess = false;
  if (navigator.clipboard && window.isSecureContext) {
    navigator.clipboard
      .writeText(text)
      .then(() => {
        if (buttonElement) {
          handleCopyResult(buttonElement, true);
        } else {
          showNotification("已复制到剪贴板", "success");
        }
      })
      .catch((err) => {
        console.error("Clipboard API failed, attempting fallback:", err);
        copySuccess = fallbackCopyTextToClipboard(text);
        if (buttonElement) {
          handleCopyResult(buttonElement, copySuccess);
        } else {
          showNotification(
            copySuccess ? "已复制到剪贴板" : "复制失败",
            copySuccess ? "success" : "error"
          );
        }
      });
  } else {
    console.warn(
      "Clipboard API not available or context insecure. Using fallback copy method."
    );
    copySuccess = fallbackCopyTextToClipboard(text);
    if (buttonElement) {
      handleCopyResult(buttonElement, copySuccess);
    } else {
      showNotification(
        copySuccess ? "已复制到剪贴板" : "复制失败",
        copySuccess ? "success" : "error"
      );
    }
  }
}

// Function to set up copy button listeners (using modern API with fallback) - Updated to handle table copy buttons
function setupCopyButtons(containerSelector = "body") {
  // Find buttons within the specified container (defaults to body)
  const container = document.querySelector(containerSelector);
  if (!container) return;

  const copyButtons = container.querySelectorAll(".copy-btn");
  copyButtons.forEach((button) => {
    // Remove existing listener to prevent duplicates if called multiple times
    button.removeEventListener("click", handleCopyButtonClick);
    // Add the listener
    button.addEventListener("click", handleCopyButtonClick);
  });
}

// Extracted click handler logic for reusability and removing listeners
function handleCopyButtonClick() {
  const button = this; // 'this' refers to the button clicked
  const targetId = button.getAttribute("data-target");
  const textToCopyDirect = button.getAttribute("data-copy-text"); // For direct text copy (e.g., table key)
  let textToCopy = "";

  if (textToCopyDirect) {
    textToCopy = textToCopyDirect;
  } else if (targetId) {
    const targetElement = document.getElementById(targetId);
    if (targetElement) {
      textToCopy = targetElement.textContent;
    } else {
      console.error("Target element not found:", targetId);
      showNotification("复制出错：找不到目标元素", "error");
      return; // Exit if target element not found
    }
  } else {
    console.error(
      "No data-target or data-copy-text attribute found on button:",
      button
    );
    showNotification("复制出错：未指定复制内容", "error");
    return; // Exit if no source specified
  }

  if (textToCopy) {
    _performCopy(textToCopy, button); // 使用新的辅助函数
  } else {
    console.warn(
      "No text found to copy for target:",
      targetId || "direct text"
    );
    showNotification("没有内容可复制", "warning");
  }
} // End of handleCopyButtonClick function

// 新增：设置批量选择相关的事件监听器
function setupBulkSelectionListeners() {
  if (selectAllCheckbox) {
    selectAllCheckbox.addEventListener("change", handleSelectAllChange);
  }

  if (tableBody) {
    // 使用事件委托处理行复选框的点击
    tableBody.addEventListener("change", handleRowCheckboxChange);
  }

  if (copySelectedKeysBtn) {
    copySelectedKeysBtn.addEventListener("click", handleCopySelectedKeys);
  }

  // 新增：为批量删除按钮添加事件监听器 (如果尚未添加)
  // 通常在 DOMContentLoaded 中添加一次即可
  // if (deleteSelectedBtn && !deleteSelectedBtn.hasListener) {
  //     deleteSelectedBtn.addEventListener('click', handleDeleteSelected);
  //     deleteSelectedBtn.hasListener = true; // 标记已添加
  // }
}

// 新增：处理"全选"复选框变化的函数
function handleSelectAllChange() {
  const isChecked = selectAllCheckbox.checked;
  const rowCheckboxes = tableBody.querySelectorAll(".row-checkbox");
  rowCheckboxes.forEach((checkbox) => {
    checkbox.checked = isChecked;
  });
  updateSelectedState();
}

// 新增：处理行复选框变化的函数 (事件委托)
function handleRowCheckboxChange(event) {
  if (event.target.classList.contains("row-checkbox")) {
    updateSelectedState();
  }
}

// 新增：更新选中状态（计数、按钮状态、全选框状态）
function updateSelectedState() {
  const rowCheckboxes = tableBody.querySelectorAll(".row-checkbox");
  const selectedCheckboxes = tableBody.querySelectorAll(
    ".row-checkbox:checked"
  );
  const selectedCount = selectedCheckboxes.length;

  // 移除了数字显示，不再更新selectedCountSpan
  // 仍然更新复制按钮的禁用状态
  if (copySelectedKeysBtn) {
    copySelectedKeysBtn.disabled = selectedCount === 0;

    // 可选：根据选中项数量更新按钮标题属性
    copySelectedKeysBtn.setAttribute("title", `复制${selectedCount}项选中密钥`);
  }
  // 新增：更新批量删除按钮的禁用状态
  if (deleteSelectedBtn) {
    deleteSelectedBtn.disabled = selectedCount === 0;
    deleteSelectedBtn.setAttribute("title", `删除${selectedCount}项选中日志`);
  }

  // 更新"全选"复选框的状态
  if (selectAllCheckbox) {
    if (rowCheckboxes.length > 0 && selectedCount === rowCheckboxes.length) {
      selectAllCheckbox.checked = true;
      selectAllCheckbox.indeterminate = false;
    } else if (selectedCount > 0) {
      selectAllCheckbox.checked = false;
      selectAllCheckbox.indeterminate = true; // 部分选中状态
    } else {
      selectAllCheckbox.checked = false;
      selectAllCheckbox.indeterminate = false;
    }
  }
}

// 新增：处理"复制选中密钥"按钮点击的函数
function handleCopySelectedKeys() {
  const selectedCheckboxes = tableBody.querySelectorAll(
    ".row-checkbox:checked"
  );
  const keysToCopy = [];
  selectedCheckboxes.forEach((checkbox) => {
    const key = checkbox.getAttribute("data-key");
    if (key) {
      keysToCopy.push(key);
    }
  });

  if (keysToCopy.length > 0) {
    const textToCopy = keysToCopy.join("\n"); // 每行一个密钥
    _performCopy(textToCopy, copySelectedKeysBtn); // 使用新的辅助函数
  } else {
    showNotification("没有选中的密钥可复制", "warning");
  }
}

// 修改：处理批量删除按钮点击的函数 - 改为显示模态框
function handleDeleteSelected() {
  const selectedCheckboxes = tableBody.querySelectorAll(
    ".row-checkbox:checked"
  );
  const logIdsToDelete = [];
  selectedCheckboxes.forEach((checkbox) => {
    const logId = checkbox.getAttribute("data-log-id"); // 需要在渲染时添加 data-log-id
    if (logId) {
      logIdsToDelete.push(parseInt(logId));
    }
  });

  if (logIdsToDelete.length === 0) {
    showNotification("没有选中的日志可删除", "warning");
    return;
  }

  if (logIdsToDelete.length === 0) {
    showNotification("没有选中的日志可删除", "warning");
    return;
  }

  // 存储待删除ID并显示模态框
  idsToDeleteGlobally = logIdsToDelete; // 仍然需要设置，因为 performActualDelete 会用到
  const message = `确定要删除选中的 ${logIdsToDelete.length} 条日志吗？此操作不可恢复！`;
  showDeleteConfirmModal(message, function() { // 传入匿名回调
    performActualDelete(idsToDeleteGlobally);
  });
}
 
// 新增：执行实际的删除操作（提取自原 handleDeleteSelected 和 handleDeleteLogRow）
async function performActualDelete(logIds) {
  if (!logIds || logIds.length === 0) return;

  const isSingleDelete = logIds.length === 1;
  const url = isSingleDelete
    ? `/api/logs/errors/${logIds[0]}`
    : "/api/logs/errors";
  const method = "DELETE";
  const body = isSingleDelete ? null : JSON.stringify({ ids: logIds });
  const headers = isSingleDelete ? {} : { "Content-Type": "application/json" };
  const options = {
    method: method,
    headers: headers,
    body: body, // fetchAPI handles null body correctly
  };

  try {
    // Use fetchAPI for the delete request
    await fetchAPI(url, options); // fetchAPI returns null for 204 No Content

    // If fetchAPI doesn't throw, the request was successful
    const successMessage = isSingleDelete
      ? `成功删除该日志`
      : `成功删除 ${logIds.length} 条日志`;
    showNotification(successMessage, "success");
    // 取消全选
    if (selectAllCheckbox) selectAllCheckbox.checked = false;
    // 重新加载当前页数据
    loadErrorLogs();
  } catch (error) {
    console.error("批量删除错误日志失败:", error);
    showNotification(`批量删除失败: ${error.message}`, "error", 5000);
  }
}

// 修改：处理单行删除按钮点击的函数 - 改为显示模态框
function handleDeleteLogRow(logId) {
  if (!logId) return;

  // 存储待删除ID并显示模态框
  idsToDeleteGlobally = [parseInt(logId)]; // 存储为数组 // 仍然需要设置，因为 performActualDelete 会用到
  // 使用通用确认消息，不显示具体ID
  const message = `确定要删除这条日志吗？此操作不可恢复！`;
  showDeleteConfirmModal(message, function() { // 传入匿名回调
    performActualDelete([parseInt(logId)]); // 确保传递的是数组
  });
}
 
// 新增：处理 ID 排序点击的函数
function handleSortById() {
  if (errorLogState.sort.field === "id") {
    // 如果当前是按 ID 排序，切换顺序
    errorLogState.sort.order =
      errorLogState.sort.order === "asc" ? "desc" : "asc";
  } else {
    // 如果当前不是按 ID 排序，切换到按 ID 排序，默认为降序
    errorLogState.sort.field = "id";
    errorLogState.sort.order = "desc";
  }
  // 更新图标
  updateSortIcon();
  // 重新加载第一页数据
  errorLogState.currentPage = 1;
  loadErrorLogs();
}

// 新增：更新排序图标的函数
function updateSortIcon() {
  if (!sortIcon) return;
  // 移除所有可能的排序类
  sortIcon.classList.remove(
    "fa-sort",
    "fa-sort-up",
    "fa-sort-down",
    "text-gray-400",
    "text-primary-600"
  );

  if (errorLogState.sort.field === "id") {
    sortIcon.classList.add(
      errorLogState.sort.order === "asc" ? "fa-sort-up" : "fa-sort-down"
    );
    sortIcon.classList.add("text-primary-600"); // 高亮显示
  } else {
    // 如果不是按 ID 排序，显示默认图标
    sortIcon.classList.add("fa-sort", "text-gray-400");
  }
}

// 加载错误日志数据
async function loadErrorLogs() {
  // 重置选择状态
  if (selectAllCheckbox) selectAllCheckbox.checked = false;
  if (selectAllCheckbox) selectAllCheckbox.indeterminate = false;
  updateSelectedState(); // 更新按钮状态和计数

  showLoading(true);
  showError(false);
  showNoData(false);

  const offset = (errorLogState.currentPage - 1) * errorLogState.pageSize;

  try {
    // Construct the API URL with search and sort parameters
    let apiUrl = `/api/logs/errors?limit=${errorLogState.pageSize}&offset=${offset}`;
    // 添加排序参数
    apiUrl += `&sort_by=${errorLogState.sort.field}&sort_order=${errorLogState.sort.order}`;

    // 添加搜索参数
    if (errorLogState.search.key) {
      apiUrl += `&key_search=${encodeURIComponent(errorLogState.search.key)}`;
    }
    if (errorLogState.search.error) {
      apiUrl += `&error_search=${encodeURIComponent(
        errorLogState.search.error
      )}`;
    }
    if (errorLogState.search.errorCode) {
      // Add error code to API request
      apiUrl += `&error_code_search=${encodeURIComponent(
        errorLogState.search.errorCode
      )}`;
    }
    if (errorLogState.search.startDate) {
      apiUrl += `&start_date=${encodeURIComponent(
        errorLogState.search.startDate
      )}`;
    }
    if (errorLogState.search.endDate) {
      apiUrl += `&end_date=${encodeURIComponent(errorLogState.search.endDate)}`;
    }

    // Use fetchAPI to get logs
    const data = await fetchAPI(apiUrl);

    // API 现在返回 { logs: [], total: count }
    // fetchAPI already parsed JSON
    if (data && Array.isArray(data.logs)) {
      errorLogState.logs = data.logs; // Store the list data (contains error_code)
      renderErrorLogs(errorLogState.logs);
      updatePagination(errorLogState.logs.length, data.total || -1); // Use total from response
    } else {
      // Handle unexpected data format even after successful fetch
      console.error("Unexpected API response format:", data);
      throw new Error("无法识别的API响应格式");
    }

    showLoading(false);

    if (errorLogState.logs.length === 0) {
      showNoData(true);
    }
  } catch (error) {
    console.error("获取错误日志失败:", error);
    showLoading(false);
    showError(true, error.message); // Show specific error message
  }
}

// Helper function to create HTML for a single log row
function _createLogRowHtml(log, sequentialId) {
  // Format date
  let formattedTime = "N/A";
  try {
    const requestTime = new Date(log.request_time);
    if (!isNaN(requestTime)) {
      formattedTime = requestTime.toLocaleString("zh-CN", {
        year: "numeric",
        month: "2-digit",
        day: "2-digit",
        hour: "2-digit",
        minute: "2-digit",
        second: "2-digit",
        hour12: false,
      });
    }
  } catch (e) {
    console.error("Error formatting date:", e);
  }

  const errorCodeContent = log.error_code || "无";

  const maskKey = (key) => {
    if (!key || key.length < 8) return key || "无";
    return `${key.substring(0, 4)}...${key.substring(key.length - 4)}`;
  };
  const maskedKey = maskKey(log.gemini_key);
  const fullKey = log.gemini_key || "";

  return `
        <td class="text-center px-3 py-3 text-gray-700">
            <input type="checkbox" class="row-checkbox form-checkbox h-4 w-4 text-blue-600 border-gray-300 rounded focus:ring-blue-500" data-key="${fullKey}" data-log-id="${
    log.id
  }">
        </td>
        <td class="text-gray-700">${sequentialId}</td>
        <td class="relative group text-gray-700" title="${fullKey}">
            ${maskedKey}
            <button class="copy-btn absolute top-1/2 right-2 transform -translate-y-1/2 bg-gray-200 hover:bg-gray-300 text-gray-600 p-1 rounded opacity-0 group-hover:opacity-100 transition-opacity text-xs" data-copy-text="${fullKey}" title="复制完整密钥">
                <i class="far fa-copy"></i>
            </button>
        </td>
        <td class="text-gray-700">${log.error_type || "未知"}</td>
        <td class="error-code-content text-gray-700" title="${
          log.error_code || ""
        }">${errorCodeContent}</td>
        <td class="text-gray-700">${log.model_name || "未知"}</td>
        <td class="text-gray-700">${formattedTime}</td>
        <td>
            <button class="btn-view-details mr-2 bg-blue-600 hover:bg-blue-700 text-white px-3 py-1 rounded text-sm transition-all duration-200" data-log-id="${log.id}">
                <i class="fas fa-eye mr-1"></i>详情
            </button>
            <button class="btn-delete-row bg-red-600 hover:bg-red-700 text-white px-2 py-1 rounded text-sm transition-all duration-200" data-log-id="${
              log.id
            }" title="删除此日志">
                <i class="fas fa-trash-alt"></i>
            </button>
        </td>
    `;
}

// 渲染错误日志表格
function renderErrorLogs(logs) {
  if (!tableBody) return;
  tableBody.innerHTML = ""; // Clear previous entries

  // 重置全选复选框状态（在清空表格后）
  if (selectAllCheckbox) {
    selectAllCheckbox.checked = false;
    selectAllCheckbox.indeterminate = false;
  }

  if (!logs || logs.length === 0) {
    // Handled by showNoData
    return;
  }

  const startIndex = (errorLogState.currentPage - 1) * errorLogState.pageSize;

  logs.forEach((log, index) => {
    const sequentialId = startIndex + index + 1;
    const row = document.createElement("tr");
    row.innerHTML = _createLogRowHtml(log, sequentialId);
    tableBody.appendChild(row);
  });

  // Add event listeners to new 'View Details' buttons
  document.querySelectorAll(".btn-view-details").forEach((button) => {
    button.addEventListener("click", function () {
      const logId = parseInt(this.getAttribute("data-log-id"));
      showLogDetails(logId);
    });
  });

  // 新增：为新渲染的删除按钮添加事件监听器
  document.querySelectorAll(".btn-delete-row").forEach((button) => {
    button.addEventListener("click", function () {
      const logId = this.getAttribute("data-log-id");
      handleDeleteLogRow(logId);
    });
  });

  // Re-initialize copy buttons specifically for the newly rendered table rows
  setupCopyButtons("#errorLogsTable");
  // Update selected state after rendering
  updateSelectedState();
}

// 显示错误日志详情 (从 API 获取)
async function showLogDetails(logId) {
  if (!logDetailModal) return;

  // Show loading state in modal (optional)
  // Clear previous content and show a spinner or message
  document.getElementById("modalGeminiKey").textContent = "加载中...";
  document.getElementById("modalErrorType").textContent = "加载中...";
  document.getElementById("modalErrorLog").textContent = "加载中...";
  document.getElementById("modalRequestMsg").textContent = "加载中...";
  document.getElementById("modalModelName").textContent = "加载中...";
  document.getElementById("modalRequestTime").textContent = "加载中...";

  logDetailModal.classList.add("show");
  document.body.style.overflow = "hidden"; // Prevent body scrolling

  try {
    // Use fetchAPI to get log details
    const logDetails = await fetchAPI(`/api/logs/errors/${logId}/details`);

    // fetchAPI handles response.ok check and JSON parsing
    if (!logDetails) {
      // Handle case where API returns success but no data (if possible)
      throw new Error("未找到日志详情");
    }

    // Format date
    let formattedTime = "N/A";
    try {
      const requestTime = new Date(logDetails.request_time);
      if (!isNaN(requestTime)) {
        formattedTime = requestTime.toLocaleString("zh-CN", {
          year: "numeric",
          month: "2-digit",
          day: "2-digit",
          hour: "2-digit",
          minute: "2-digit",
          second: "2-digit",
          hour12: false,
        });
      }
    } catch (e) {
      console.error("Error formatting date:", e);
    }

    // Format request message (handle potential JSON)
    let formattedRequestMsg = "无";
    if (logDetails.request_msg) {
      try {
        if (
          typeof logDetails.request_msg === "object" &&
          logDetails.request_msg !== null
        ) {
          formattedRequestMsg = JSON.stringify(logDetails.request_msg, null, 2);
        } else if (typeof logDetails.request_msg === "string") {
          // Try parsing if it looks like JSON, otherwise display as string
          const trimmedMsg = logDetails.request_msg.trim();
          if (trimmedMsg.startsWith("{") || trimmedMsg.startsWith("[")) {
            formattedRequestMsg = JSON.stringify(
              JSON.parse(logDetails.request_msg),
              null,
              2
            );
          } else {
            formattedRequestMsg = logDetails.request_msg;
          }
        } else {
          formattedRequestMsg = String(logDetails.request_msg);
        }
      } catch (e) {
        formattedRequestMsg = String(logDetails.request_msg); // Fallback
        console.warn("Could not parse request_msg as JSON:", e);
      }
    }

    // Populate modal content with fetched details
    document.getElementById("modalGeminiKey").textContent =
      logDetails.gemini_key || "无";
    document.getElementById("modalErrorType").textContent =
      logDetails.error_type || "未知";
    document.getElementById("modalErrorLog").textContent =
      logDetails.error_log || "无"; // Full error log
    document.getElementById("modalRequestMsg").textContent =
      formattedRequestMsg; // Full request message
    document.getElementById("modalModelName").textContent =
      logDetails.model_name || "未知";
    document.getElementById("modalRequestTime").textContent = formattedTime;

    // Re-initialize copy buttons specifically for the modal after content is loaded
    setupCopyButtons("#logDetailModal");
  } catch (error) {
    console.error("获取日志详情失败:", error);
    // Show error in modal
    document.getElementById("modalGeminiKey").textContent = "错误";
    document.getElementById("modalErrorType").textContent = "错误";
    document.getElementById(
      "modalErrorLog"
    ).textContent = `加载失败: ${error.message}`;
    document.getElementById("modalRequestMsg").textContent = "错误";
    document.getElementById("modalModelName").textContent = "错误";
    document.getElementById("modalRequestTime").textContent = "错误";
    // Optionally show a notification
    showNotification(`加载日志详情失败: ${error.message}`, "error", 5000);
  }
}

// Close Log Detail Modal
function closeLogDetailModal() {
  if (logDetailModal) {
    logDetailModal.classList.remove("show");
    // Optional: Restore body scrolling
    document.body.style.overflow = "";
  }
}

// 更新分页控件
function updatePagination(currentItemCount, totalItems) {
  if (!paginationElement) return;
  paginationElement.innerHTML = ""; // Clear existing pagination

  // Calculate total pages only if totalItems is known and valid
  let totalPages = 1;
  if (totalItems >= 0) {
    totalPages = Math.max(1, Math.ceil(totalItems / errorLogState.pageSize));
  } else if (
    currentItemCount < errorLogState.pageSize &&
    errorLogState.currentPage === 1
  ) {
    // If less items than page size fetched on page 1, assume it's the only page
    totalPages = 1;
  } else {
    // If total is unknown and more items might exist, we can't build full pagination
    // We can show Prev/Next based on current page and if items were returned
    console.warn("Total item count unknown, pagination will be limited.");
    // Basic Prev/Next for unknown total
    addPaginationLink(
      paginationElement,
      "&laquo;",
      errorLogState.currentPage > 1,
      () => {
        errorLogState.currentPage--;
        loadErrorLogs();
      }
    );
    addPaginationLink(
      paginationElement,
      errorLogState.currentPage.toString(),
      true,
      null,
      true
    ); // Current page number (non-clickable)
    addPaginationLink(
      paginationElement,
      "&raquo;",
      currentItemCount === errorLogState.pageSize,
      () => {
        errorLogState.currentPage++;
        loadErrorLogs();
      }
    ); // Next enabled if full page was returned
    return; // Exit here for limited pagination
  }

  const maxPagesToShow = 5; // Max number of page links to show
  let startPage = Math.max(
    1,
    errorLogState.currentPage - Math.floor(maxPagesToShow / 2)
  );
  let endPage = Math.min(totalPages, startPage + maxPagesToShow - 1);

  // Adjust startPage if endPage reaches the limit first
  if (endPage === totalPages) {
    startPage = Math.max(1, endPage - maxPagesToShow + 1);
  }

  // Previous Button
  addPaginationLink(
    paginationElement,
    "&laquo;",
    errorLogState.currentPage > 1,
    () => {
      errorLogState.currentPage--;
      loadErrorLogs();
    }
  );

  // First Page Button
  if (startPage > 1) {
    addPaginationLink(paginationElement, "1", true, () => {
      errorLogState.currentPage = 1;
      loadErrorLogs();
    });
    if (startPage > 2) {
      addPaginationLink(paginationElement, "...", false); // Ellipsis
    }
  }

  // Page Number Buttons
  for (let i = startPage; i <= endPage; i++) {
    addPaginationLink(
      paginationElement,
      i.toString(),
      true,
      () => {
        errorLogState.currentPage = i;
        loadErrorLogs();
      },
      i === errorLogState.currentPage
    );
  }

  // Last Page Button
  if (endPage < totalPages) {
    if (endPage < totalPages - 1) {
      addPaginationLink(paginationElement, "...", false); // Ellipsis
    }
    addPaginationLink(paginationElement, totalPages.toString(), true, () => {
      errorLogState.currentPage = totalPages;
      loadErrorLogs();
    });
  }

  // Next Button
  addPaginationLink(
    paginationElement,
    "&raquo;",
    errorLogState.currentPage < totalPages,
    () => {
      errorLogState.currentPage++;
      loadErrorLogs();
    }
  );
}

// Helper function to add pagination links
function addPaginationLink(
  parentElement,
  text,
  enabled,
  clickHandler,
  isActive = false
) {
  // const pageItem = document.createElement('li'); // We are not using <li> anymore

  const pageLink = document.createElement("a");

  // Base Tailwind classes for layout, size, and transition. Colors/borders will come from CSS.
  let baseClasses =
    "px-3 py-1 rounded-md text-sm transition duration-150 ease-in-out"; // Common classes

  if (isActive) {
    pageLink.className = `${baseClasses} active`; // Add 'active' class for CSS
  } else if (enabled) {
    pageLink.className = baseClasses; // Just base classes, CSS handles the rest
  } else {
    // Disabled link (e.g., '...' or unavailable prev/next)
    pageLink.className = `${baseClasses} disabled`; // Add 'disabled' class for CSS
  }

  pageLink.href = "#"; // Prevent page jump
  pageLink.innerHTML = text;

  if (enabled && clickHandler) {
    pageLink.addEventListener("click", function (e) {
      e.preventDefault();
      clickHandler();
    });
  } else {
    // Handles !enabled (includes isActive as clickHandler is null for it, and '...' which has no clickHandler)
    pageLink.addEventListener("click", (e) => e.preventDefault());
  }

  parentElement.appendChild(pageLink); // Directly append <a> to the <ul>
}

// 显示/隐藏状态指示器 (using 'active' class)
function showLoading(show) {
  if (loadingIndicator)
    loadingIndicator.style.display = show ? "block" : "none";
}

function showNoData(show) {
  if (noDataMessage) noDataMessage.style.display = show ? "block" : "none";
}

function showError(show, message = "加载错误日志失败，请稍后重试。") {
  if (errorMessage) {
    errorMessage.style.display = show ? "block" : "none";
    if (show) {
      // Update the error message content
      const p = errorMessage.querySelector("p");
      if (p) p.textContent = message;
    }
  }
}

// Function to show temporary status notifications (like copy success)
function showNotification(message, type = "success", duration = 3000) {
  const notificationElement = document.getElementById("notification"); // Use the correct ID from base.html
  if (!notificationElement) {
    console.error("Notification element with ID 'notification' not found.");
    return;
  }

  // Set message and type class
  notificationElement.textContent = message;
  // Remove previous type classes before adding the new one
  notificationElement.classList.remove("success", "error", "warning", "info");
  notificationElement.classList.add(type); // Add the type class for styling
  notificationElement.className = `notification ${type} show`; // Add 'show' class

  // Hide after duration
  setTimeout(() => {
    notificationElement.classList.remove("show");
  }, duration);
}

// Example Usage (if copy functionality is added later):
// showNotification('密钥已复制!', 'success');
// showNotification('复制失败!', 'error');
