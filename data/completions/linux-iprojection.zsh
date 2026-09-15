#compdef linux-iprojection

_linux_iprojection() {
    local -a commands
    commands=(
        'discover:Discover Epson and PJLink projectors on local network'
        'power:Control or query projector power state'
        'source:Switch or query projector input source'
        'volume:Adjust or query projector speaker volume'
        'mute:Toggle or set A/V mute state'
        'freeze:Toggle or set video screen freeze'
        'cast:Stream desktop screen and audio over PipeWire/RTP'
        'status:Query comprehensive status and telemetry'
        'firewall:Inspect and configure Linux firewall rules'
        'macro:Execute automated macro command sequence'
        'daemon:Run D-Bus session background daemon'
        'tui:Launch interactive terminal status dashboard'
    )

    _arguments -C \
        '1: :->command' \
        '*: :->args'

    case $state in
        command)
            _describe -t commands 'linux-iprojection command' commands
            ;;
        args)
            case $line[1] in
                power)
                    _values 'power state' 'on' 'off' 'standby' 'query' 'status'
                    ;;
                source)
                    _values 'source' 'hdmi1' 'hdmi2' 'vga1' 'vga2' 'usb' 'displayport' 'lan' 'wireless' 'auto'
                    ;;
                cast)
                    _arguments \
                        '--encoder[Video encoder]:encoder:(vaapi nvenc x264 auto)' \
                        '--framerate[Target FPS]:fps:(30 60 24)' \
                        '--bitrate[Target bitrate kbps]:bitrate:(4000 8000 12000)' \
                        '--audio[Enable audio loopback]' \
                        '--host[Projector IP address]:host:_hosts'
                    ;;
            esac
            ;;
    esac
}

_linux_iprojection "$@"
