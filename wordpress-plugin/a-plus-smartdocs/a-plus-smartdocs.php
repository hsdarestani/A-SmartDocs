<?php
/**
 * Plugin Name: A+ SmartDocs Portal
 * Description: Verbindet die A+ Solution WordPress-Website mit dem SmartDocs-Kundenportal.
 * Version: 0.1.0
 * Author: A+ Solution GmbH
 * Text Domain: a-plus-smartdocs
 */

if (!defined('ABSPATH')) {
    exit;
}

final class A_Plus_SmartDocs_Portal {
    private const OPTION_URL = 'a_plus_smartdocs_portal_url';

    public function __construct() {
        add_action('admin_menu', [$this, 'admin_menu']);
        add_action('admin_init', [$this, 'register_settings']);
        add_action('wp_enqueue_scripts', [$this, 'enqueue_assets']);
        add_shortcode('a_plus_smartdocs_portal', [$this, 'shortcode']);
        add_filter('woocommerce_account_menu_items', [$this, 'konto_menu']);
        add_action('init', [$this, 'konto_endpunkt']);
        add_action('woocommerce_account_smartdocs_endpoint', [$this, 'konto_inhalt']);
    }

    public function portal_url(): string {
        return esc_url(get_option(self::OPTION_URL, 'https://smartdocs.aplus-solution.de'));
    }

    public function admin_menu(): void {
        add_options_page(
            'A+ SmartDocs',
            'A+ SmartDocs',
            'manage_options',
            'a-plus-smartdocs',
            [$this, 'settings_page']
        );
    }

    public function register_settings(): void {
        register_setting('a_plus_smartdocs', self::OPTION_URL, [
            'type' => 'string',
            'sanitize_callback' => 'esc_url_raw',
            'default' => 'https://smartdocs.aplus-solution.de',
        ]);
    }

    public function settings_page(): void {
        ?>
        <div class="wrap">
            <h1>A+ SmartDocs Portal</h1>
            <p>Hier wird die Adresse des SmartDocs-Kundenportals festgelegt.</p>
            <form method="post" action="options.php">
                <?php settings_fields('a_plus_smartdocs'); ?>
                <table class="form-table" role="presentation">
                    <tr>
                        <th scope="row"><label for="a_plus_smartdocs_portal_url">Portal-Adresse</label></th>
                        <td><input class="regular-text" type="url" id="a_plus_smartdocs_portal_url" name="<?php echo esc_attr(self::OPTION_URL); ?>" value="<?php echo esc_attr($this->portal_url()); ?>"></td>
                    </tr>
                </table>
                <?php submit_button('Einstellungen speichern'); ?>
            </form>
            <p><strong>Verfügbarer Kurzcode:</strong> <code>[a_plus_smartdocs_portal]</code></p>
        </div>
        <?php
    }

    public function enqueue_assets(): void {
        wp_register_style(
            'a-plus-smartdocs-portal',
            plugins_url('assets/portal.css', __FILE__),
            [],
            '0.1.0'
        );
    }

    public function shortcode(array $attributes = []): string {
        wp_enqueue_style('a-plus-smartdocs-portal');
        $attributes = shortcode_atts([
            'titel' => 'Dokumente automatisch erstellen',
            'text' => 'Bestehende PDF- und Bildvorlagen intelligent erkennen, ausfüllen und wiederverwenden.',
        ], $attributes, 'a_plus_smartdocs_portal');

        ob_start();
        ?>
        <section class="aplus-smartdocs-portal">
            <div class="aplus-smartdocs-zeichen">A+</div>
            <div class="aplus-smartdocs-inhalt">
                <span>A+ SMARTDOCS</span>
                <h2><?php echo esc_html($attributes['titel']); ?></h2>
                <p><?php echo esc_html($attributes['text']); ?></p>
                <div class="aplus-smartdocs-aktionen">
                    <a class="aplus-smartdocs-primaer" href="<?php echo esc_url($this->portal_url() . '/registrieren'); ?>">14 Tage kostenlos testen</a>
                    <a class="aplus-smartdocs-sekundaer" href="<?php echo esc_url($this->portal_url() . '/anmelden'); ?>">Zum Kundenportal</a>
                </div>
            </div>
        </section>
        <?php
        return (string) ob_get_clean();
    }

    public function konto_endpunkt(): void {
        add_rewrite_endpoint('smartdocs', EP_ROOT | EP_PAGES);
    }

    public function konto_menu(array $items): array {
        $logout = $items['customer-logout'] ?? null;
        unset($items['customer-logout']);
        $items['smartdocs'] = 'A+ SmartDocs';
        if ($logout !== null) {
            $items['customer-logout'] = $logout;
        }
        return $items;
    }

    public function konto_inhalt(): void {
        echo do_shortcode('[a_plus_smartdocs_portal titel="Ihr SmartDocs-Arbeitsbereich" text="Vorlagen verwalten, Dokumente erstellen und Teamzugänge steuern."]');
    }
}

new A_Plus_SmartDocs_Portal();
