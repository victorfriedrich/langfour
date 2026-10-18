//
//  ViewController.swift
//  Langfour Reader
//
//  Created by Victor Friedrich on 06.10.26.
//

import UIKit
import WebKit

class ViewController: UIViewController, WKNavigationDelegate, WKScriptMessageHandler {

    @IBOutlet var webView: WKWebView!

    override func viewDidLoad() {
        super.viewDidLoad()

        self.webView.navigationDelegate = self
        // The setup guide is taller than small phones.
        self.webView.scrollView.isScrollEnabled = true
        self.webView.isOpaque = false
        self.webView.backgroundColor = .systemBackground

        self.webView.configuration.userContentController.add(self, name: "controller")

        self.webView.loadFileURL(Bundle.main.url(forResource: "Main", withExtension: "html")!, allowingReadAccessTo: Bundle.main.resourceURL!)
    }

    // Main.html's buttons open their link in Safari, where the extension runs.
    func userContentController(_ userContentController: WKUserContentController, didReceive message: WKScriptMessage) {
        guard let body = message.body as? [String: Any] else { return }
        guard let link = body["open"] as? String,
              let url = URL(string: link),
              url.scheme == "https" else { return }
        UIApplication.shared.open(url)
    }

}
