sub init()
    m.top.functionName = "go"
end sub

sub go()
    port = CreateObject("roMessagePort")
    ut = CreateObject("roUrlTransfer")
    ut.SetMessagePort(port)
    ut.SetUrl(m.top.url)
    if not ut.AsyncGetToFile(m.top.file)
        m.top.result = "error:start"
        return
    end if
    msg = wait(20000, port)
    if type(msg) = "roUrlEvent" and msg.GetResponseCode() = 200
        m.top.result = m.top.file
    else
        ut.AsyncCancel()
        code = "timeout"
        if type(msg) = "roUrlEvent" then code = msg.GetResponseCode().ToStr()
        m.top.result = "error:" + code
    end if
end sub
