' Every tick a background Fetcher downloads the dashboard image to tmp:/ (alternating
' two file names so the Poster sees a new uri), then the hidden Poster loads that local
' file and is swapped in only once ready - so the screen never flashes blank, and if a
' download fails the last good frame stays up.
sub init()
    m.posters = [m.top.findNode("a"), m.top.findNode("b")]
    m.msg = m.top.findNode("msg")
    m.front = 0
    m.loading = -1
    m.shown = false
    m.fails = 0
    m.busy = false
    for each p in m.posters
        p.observeField("loadStatus", "onLoadStatus")
    end for
    m.tick = m.top.findNode("tick")
    m.tick.observeField("fire", "refresh")
    m.tick.control = "start"
    refresh()
end sub

sub refresh()
    if m.busy then return
    m.busy = true
    m.next = 1 - m.front
    f = CreateObject("roSGNode", "Fetcher")
    f.url = m.top.imageUrl + "?t=" + CreateObject("roDateTime").AsSeconds().ToStr()
    f.file = "tmp:/dash-" + m.next.ToStr() + "-" + CreateObject("roDateTime").AsSeconds().ToStr() + ".jpg"
    f.observeField("result", "onFetched")
    m.fetcher = f
    f.control = "run"
end sub

sub onFetched(event as object)
    m.busy = false
    res = event.getData()
    if Left(res, 6) = "error:"
        fail(res)
        return
    end if
    old = m.posters[m.next].uri
    m.loading = m.next
    m.posters[m.next].uri = res
    if old <> "" and Left(old, 5) = "tmp:/" then DeleteFile(old)
end sub

sub onLoadStatus(event as object)
    status = event.getData()
    p = event.getRoSGNode()
    if m.loading < 0 or not p.isSameNode(m.posters[m.loading]) then return
    if status = "ready"
        p.visible = true
        m.posters[m.front].visible = false
        m.front = m.loading
        m.loading = -1
        m.shown = true
        m.fails = 0
        m.msg.visible = false
    else if status = "failed"
        m.loading = -1
        fail("decode")
    end if
end sub

sub fail(why as string)
    m.fails = m.fails + 1
    print "dashboard: refresh failed ("; m.fails; ") "; why
    if not m.shown
        m.msg.text = "Can't load the family dashboard yet - retrying (" + m.fails.ToStr() + ")"
    end if
end sub
