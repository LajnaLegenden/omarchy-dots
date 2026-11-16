-- Called by voice-show through `nvim --server … --remote-expr`.
-- Opens a file in a normal window, jumps to `first`, and highlights first..last.
local ns = vim.api.nvim_create_namespace("claude_voice_show")

return function(path, first, last)
  -- Prefer a regular file window over sidebars/pickers.
  if vim.bo.buftype ~= "" then
    for _, win in ipairs(vim.api.nvim_tabpage_list_wins(0)) do
      if vim.bo[vim.api.nvim_win_get_buf(win)].buftype == "" then
        vim.api.nvim_set_current_win(win)
        break
      end
    end
  end
  vim.cmd("stopinsert")
  vim.cmd("edit " .. vim.fn.fnameescape(path))

  local buf = vim.api.nvim_get_current_buf()
  local count = vim.api.nvim_buf_line_count(buf)
  first = math.max(1, math.min(tonumber(first) or 1, count))
  last = math.max(first, math.min(tonumber(last) or first, count))

  for _, b in ipairs(vim.api.nvim_list_bufs()) do
    if vim.api.nvim_buf_is_loaded(b) then
      vim.api.nvim_buf_clear_namespace(b, ns, 0, -1)
    end
  end
  for line = first, last do
    vim.api.nvim_buf_set_extmark(buf, ns, line - 1, 0, { line_hl_group = "Visual", priority = 200 })
  end

  vim.api.nvim_win_set_cursor(0, { first, 0 })
  -- Center a short range; for a long one, put its start near the top.
  if last - first + 1 < vim.api.nvim_win_get_height(0) / 2 then
    vim.cmd("normal! zz")
  else
    vim.cmd("normal! zt")
  end
  vim.cmd("redraw")
  return string.format("showing %s lines %d-%d", vim.fn.expand("%:~:."), first, last)
end
