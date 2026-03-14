# ── lib/cmd_deploy.sh ───────────────────────────────────────────────────────
# Commande : sudo bash game_commander.sh deploy [--config FILE]

cmd_deploy() {
    deploy_set_defaults

    local _args=("$@")
    local i=0
    while [[ $i -lt ${#_args[@]} ]]; do
        case "${_args[$i]}" in
            --config)
                i=$((i+1))
                CONFIG_FILE_DEPLOY="${_args[$i]}"
                CONFIG_MODE=true
                ;;
            --attach|--existing-server)
                DEPLOY_MODE="attach"
                ;;
            --generate-config)
                deploy_handle_special_args "${_args[$((i+1))]:-env/deploy_config.env}"
                return 0
                ;;
        esac
        i=$((i+1))
    done

    deploy_load_config_file
    deploy_init_logging
    deploy_print_banner

    hdr "ÉTAPE 1 : Environnement"
    [[ -f /etc/os-release ]] && { . /etc/os-release; OS_ID="${ID:-unknown}"; OS_PRETTY="${PRETTY_NAME:-Linux}"; } \
                              || { OS_ID="unknown"; OS_PRETTY="Linux"; }
    info "Système : $OS_PRETTY"
    [[ "$OS_ID" != "ubuntu" ]] && { warn "Optimisé pour Ubuntu."; confirm "Continuer ?" "o" || die "Annulé."; }

    deploy_step_configuration

    deploy_step_dependencies
    deploy_step_game_install
    deploy_step_game_service
    deploy_step_backups
    deploy_step_app_files
    deploy_step_app_service
    deploy_step_nginx
    deploy_step_ssl
    deploy_step_sudoers
    deploy_step_save_config
    deploy_step_validation
}
