# bash completion for linux-iprojection
_linux_iprojection_completion() {
    local cur prev words cword
    _init_completion || return

    local commands="discover power source volume mute freeze cast status firewall macro daemon tui"
    local sources="hdmi1 hdmi2 vga1 vga2 usb displayport lan wireless auto"
    local power_actions="on off standby query status reboot"

    case "${prev}" in
        linux-iprojection)
            COMPREPLY=( $(compgen -W "${commands}" -- "${cur}") )
            return 0
            ;;
        power)
            COMPREPLY=( $(compgen -W "${power_actions}" -- "${cur}") )
            return 0
            ;;
        source)
            COMPREPLY=( $(compgen -W "${sources}" -- "${cur}") )
            return 0
            ;;
        --source|-s)
            COMPREPLY=( $(compgen -W "${sources}" -- "${cur}") )
            return 0
            ;;
        --encoder|-e)
            COMPREPLY=( $(compgen -W "vaapi nvenc x264 auto" -- "${cur}") )
            return 0
            ;;
        --resolution|-r)
            COMPREPLY=( $(compgen -W "1080p 720p 4k native" -- "${cur}") )
            return 0
            ;;
        --firewall)
            COMPREPLY=( $(compgen -W "ufw firewalld status test check" -- "${cur}") )
            return 0
            ;;
    esac

    if [[ "${cur}" == -* ]]; then
        COMPREPLY=( $(compgen -W "--host --port --password --timeout --json --debug --verbose --help" -- "${cur}") )
        return 0
    fi
}

complete -F _linux_iprojection_completion linux-iprojection
