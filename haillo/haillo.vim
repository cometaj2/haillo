" 'vim -S haillo.vim -c "Haillo"' to launch directly

let mapleader = ","

" models window
let s:models = 0
let s:models_buf = -1

" conversations window
let s:conversations = 0
let s:conversations_buf = -1

" context window refresh
let s:context_buf = -1
let s:context_timer = -1
let s:refresh_ms = 2000


function! s:haillo() abort
    call s:create_context_window()
    call s:start_context_refresh(s:refresh_ms)
    call s:create_question_window()
endfunction


function! s:start_context_refresh(ms) abort
    call s:stop_context_refresh()
    let s:context_timer = timer_start(a:ms, function('s:get_context'), {'repeat': -1})
endfunction


function! s:stop_context_refresh() abort
    if s:context_timer != -1
        call timer_stop(s:context_timer)
        let s:context_timer = -1
    endif
endfunction


function! s:create_context_window() abort
    let l:buf_name = 'context'
    let l:win_num = bufwinnr(l:buf_name)

    " If the window is already open, close it
    if l:win_num != -1
        execute l:win_num . 'wincmd w'
        close
        return
    endif

    " Open a new window for the context
    execute 'vertical botright new ' . l:buf_name

    " stop the user from editing the buffer
    setlocal nomodifiable

    " tell Vim this is a temporary buffer not backed by a file
    setlocal buftype=nofile
    setlocal bufhidden=wipe
    setlocal noswapfile
    setlocal nonumber
    setlocal nowrap
    setlocal nospell

    let s:context_buf = bufnr('%')
    autocmd BufWipeout <buffer> call s:stop_context_refresh()

    call s:get_context()

    :bd 1
endfunction


function! s:get_context(...) abort
    if s:context_buf < 0 || !bufexists(s:context_buf)
        call s:stop_context_refresh()
        return
    endif

    let l:winid = bufwinid(s:context_buf)
    let l:follow = 0
    if l:winid != -1
        let l:info = getwininfo(l:winid)[0]
        let l:follow = l:info.botline >= getbufinfo(s:context_buf)[0].linecount
    endif

    let s:context_changed = 0
    python3 << trim EOF
        from huckle import cli
        import vim

        bufnr = int(vim.eval('s:context_buf'))
        buf = vim.buffers[bufnr]

        chunks = cli("hai context")
        context_str = ""
        for dest, chunk in chunks:
            if dest == 'stdout':
                context_str += chunk.decode()

        new_lines = context_str.splitlines()
        if list(buf) != new_lines:
            buf.options['modifiable'] = True
            buf[:] = new_lines
            buf.options['modifiable'] = False
            vim.command('let s:context_changed = 1')
    EOF

    if s:context_changed && l:follow && l:winid != -1
        call win_execute(l:winid, 'keepjumps normal! G')
    endif
endfunction


function! s:create_question_window() abort
    let l:buf_name = 'question'
    let l:win_num = bufwinnr(l:buf_name)

    " If the window is already open, close it
    if l:win_num != -1
        execute l:win_num . 'wincmd w'
        close
        return
    endif

    " Open a new questions input text area
    execute 'botright 5split ' . l:buf_name

    " Configure the buffer as a temporary scratchpad
    setlocal buftype=nofile
    setlocal bufhidden=hide
    setlocal noswapfile
    setlocal nowrap
    setlocal number
    nnoremap <buffer> <CR> :call <SID>chat(join(getline(1, '$'), "\n"))<CR>
endfunction



""""""""""""""""""""""""""""
" Models window related code
""""""""""""""""""""""""""""
function! s:create_models_window() abort
    let l:buf_name = 'models'
    let l:win_num = bufwinnr(l:buf_name)
    if l:win_num != -1
        execute l:win_num . 'wincmd w'
        close
        return
    endif

    " Create, then pin to far left at full height (left of context + question)
    execute 'topleft 28vnew ' . l:buf_name
    wincmd H
    execute 'vertical resize 30'

    setlocal nomodifiable
    setlocal buftype=nofile
    setlocal bufhidden=wipe
    setlocal noswapfile
    setlocal nonumber
    setlocal nowrap
    setlocal nospell
    setlocal winfixwidth
    let s:models_buf = bufnr('%')
    call s:get_models()

    set cursorline
    highlight CursorLine cterm=NONE ctermbg=darkgray guibg=#2c2c2c

    nnoremap <buffer> <CR> :call <SID>select_model(getline('.'))<CR>
endfunction


function! s:select_model(name) abort
    let l:name = trim(a:name)
    if empty(l:name)
        return
    endif
    python3 << trim EOF
        from huckle import cli
        import vim
        name = vim.eval('l:name')
        for dest, chunk in cli(f"hai model set {name}"):
            pass
    EOF
    call s:toggle_models()
endfunction


function! s:toggle_models() abort
    if s:models == 0
        call s:create_models_window()
        let s:models = 1
    else
        call s:close_models_window()
        let s:models = 0
    endif
endfunction
nnoremap <leader>m :call <SID>toggle_models()<CR>


function! s:close_models_window() abort
    let l:win_num = bufwinnr('models')
    if l:win_num != -1
        execute l:win_num . 'wincmd w'
        close
    endif
    let s:models_buf = -1
endfunction


function! s:get_models() abort
    if s:models_buf < 0 || !bufexists(s:models_buf)
        return
    endif
    python3 << trim EOF
        from huckle import cli
        import vim
        bufnr = int(vim.eval('s:models_buf'))
        buf = vim.buffers[bufnr]
        chunks = cli("hai model ls")
        out = ""
        for dest, chunk in chunks:
            if dest == 'stdout':
                out += chunk.decode()
        buf.options['modifiable'] = True
        buf[:] = out.splitlines()
        buf.options['modifiable'] = False
    EOF
endfunction
""""""""""""""""""""""""""""


"""""""""""""""""""""""""""""""""""
" Conversations window related code
"""""""""""""""""""""""""""""""""""
function! s:create_conversations_window() abort
    let l:buf_name = 'conversations'
    let l:win_num = bufwinnr(l:buf_name)
    if l:win_num != -1
        execute l:win_num . 'wincmd w'
        close
        return
    endif

    " Create, then pin to far left at full height (left of context + question)
    execute 'topleft vnew ' . l:buf_name
    wincmd H
    execute 'vertical resize ' . &columns

    setlocal nomodifiable
    setlocal buftype=nofile
    setlocal bufhidden=wipe
    setlocal noswapfile
    setlocal nonumber
    setlocal nowrap
    setlocal nospell
    setlocal winfixwidth
    let s:conversations_buf = bufnr('%')
    call s:get_conversations()

    set cursorline
    highlight CursorLine cterm=NONE ctermbg=darkgray guibg=#2c2c2c

    nnoremap <buffer> <CR> :call <SID>select_conversation(matchstr(getline('.'), '\v^\s*\zs\S+'))<CR>
endfunction


function! s:close_conversations_window() abort
    let l:win_num = bufwinnr('conversations')
    if l:win_num != -1
        execute l:win_num . 'wincmd w'
        close
    endif
    let s:conversations_buf = -1
endfunction


function! s:get_conversations() abort
    if s:conversations_buf < 0 || !bufexists(s:conversations_buf)
        return
    endif
    python3 << trim EOF
        from huckle import cli
        import vim
        bufnr = int(vim.eval('s:conversations_buf'))
        buf = vim.buffers[bufnr]
        chunks = cli("hai ls")
        out = ""
        for dest, chunk in chunks:
            if dest == 'stdout':
                out += chunk.decode()
        buf.options['modifiable'] = True
        buf[:] = out.splitlines()
        buf.options['modifiable'] = False
    EOF
endfunction


function! s:select_conversation(name) abort
    let l:name = trim(a:name)
    if empty(l:name)
        return
    endif
    python3 << trim EOF
        from huckle import cli
        import vim
        name = vim.eval('l:name')
        for dest, chunk in cli(f"hai set {name}"):
            pass
    EOF
    call s:toggle_conversations()
endfunction


function! s:toggle_conversations() abort
    if s:conversations == 0
        call s:create_conversations_window()
        let s:conversations = 1
    else
        call s:close_conversations_window()
        let s:conversations = 0
    endif
endfunction
nnoremap <leader>c :call <SID>toggle_conversations()<CR>

"""""""""""""""""""""""""""""""""""


function! s:reset_current_context() abort
    python3 << trim EOF
        from huckle import cli
        import vim
        buf = vim.buffers[bufnr]
        chunks = cli("hai reset")
    EOF
endfunction
nnoremap <leader>r :call <SID>reset_current_context()<CR>



function! s:chat(param) abort
    python3 << trim EOF
        import io
        import vim
        from huckle import cli, stdin

        py_lines = vim.eval('a:param')
        stream = io.BytesIO(py_lines.encode('utf-8'))
        with stdin(stream):
            chunks = cli(f"hai --async")
    EOF
    silent! %delete _
    call setline(1, '')
endfunction


function! s:close_all_and_quit()
    " Delete all listed buffers
    let s:buffers = getbufinfo({'buflisted': 1})
    for s:buf in s:buffers
        execute 'bdelete ' . s:buf.bufnr
    endfor
    quit
endfunction


nnoremap <leader>a :call <SID>toggle_assist()<CR>
function! s:toggle_assist() abort
    python3 << trim EOF
        from huckle import cli
        status = None
        for dest, chunk in cli('hai assist status'):
            status = chunk.decode()
        if status == "False":
            cli('hai assist start')
        elif status == "True":
            cli('hai assist stop')
    EOF
endfunction


" Overwrite :q command
command! -bang Q call s:close_all_and_quit()
cabbrev q Q

" Fast window switching using Ctrl + h/j/k/l
nnoremap <C-h> :wincmd h<CR>
nnoremap <C-j> :wincmd j<CR>
nnoremap <C-k> :wincmd k<CR>
nnoremap <C-l> :wincmd l<CR>

command! -nargs=0 Haillo call s:haillo()
