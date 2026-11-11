' Normal launch (Home screen / ECP launch/dev)
sub Main()
    showDashboard()
end sub

' Roku screensaver entry point: same dashboard, shown when the TV is idle
sub RunScreenSaver()
    showDashboard()
end sub

sub showDashboard()
    screen = CreateObject("roSGScreen")
    port = CreateObject("roMessagePort")
    screen.setMessagePort(port)
    screen.CreateScene("MainScene")
    screen.show()
    while true
        msg = wait(0, port)
        if type(msg) = "roSGScreenEvent" and msg.isScreenClosed() then return
    end while
end sub
