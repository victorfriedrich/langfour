import XCTest

/// Drives Settings, Safari and the container app from a step list, so the
/// Safari extension can be exercised end to end in the simulator without
/// writing a new test per scenario.
///
///     TEST_RUNNER_STEPS='safari;url:https://en.wikipedia.org/wiki/Madrid;shot:page' \
///     TEST_RUNNER_OUT=/tmp/out \
///     xcodebuild test -scheme "Langfour Reader" -only-testing:LangfourReaderUITests/StepRunnerUITests ...
///
/// Steps, separated by ";":
///   settings | safari | container       bring that app to the front
///   settingsfresh | safarifresh         relaunch it first
///   url:<url>                           open a URL (in Safari)
///   tap:<label>                         tap the first element whose label or identifier matches
///   tapcontains:<text>                  tap the first element whose label contains text
///   tapif:<label>                       like tap, but skip if absent
///   tapxy:<x>,<y>                       tap at normalized coordinates of the front app
///   rotate:landscape | rotate:portrait  turn the simulated device
///   taptext:<y1>,<y2>[,<n>]             tap the first (or nth) text of 3+ letters centred between y1 and y2 points
///   drag:<x1>,<y1>,<x2>,<y2>            drag between normalized coordinates
///   toggle:<label>                      switch on the switch with that label, if off
///   type:<text>                         type into the focused element
///   backspace:<n> | return              press delete n times, or Return
///   swipeup | swipedown                 scroll the front app
///   wait:<seconds>
///   shot:<name>                         save <OUT>/<name>.png
///   dump:<name>                         save <OUT>/<name>.txt with the accessibility tree
final class StepRunnerUITests: XCTestCase {
    private var front: XCUIApplication = XCUIApplication(bundleIdentifier: "com.apple.mobilesafari")
    private var outDir: URL!

    func testRunSteps() throws {
        let env = ProcessInfo.processInfo.environment
        let steps = (env["STEPS"] ?? "").split(separator: ";").map(String.init)
        outDir = URL(fileURLWithPath: env["OUT"] ?? NSTemporaryDirectory())
        try FileManager.default.createDirectory(at: outDir, withIntermediateDirectories: true)
        continueAfterFailure = false

        for (index, step) in steps.enumerated() {
            try run(step, index: index)
        }
    }

    private func run(_ step: String, index: Int) throws {
        let parts = step.split(separator: ":", maxSplits: 1).map(String.init)
        let command = parts[0]
        let arg = parts.count > 1 ? parts[1] : ""
        NSLog("STEP \(index): \(step)")

        switch command {
        case "settings":
            front = XCUIApplication(bundleIdentifier: "com.apple.Preferences")
            front.activate()
        case "settingsfresh":
            front = XCUIApplication(bundleIdentifier: "com.apple.Preferences")
            front.terminate()
            front.activate()
        case "safari":
            front = XCUIApplication(bundleIdentifier: "com.apple.mobilesafari")
            front.activate()
        case "safarifresh":
            front = XCUIApplication(bundleIdentifier: "com.apple.mobilesafari")
            front.terminate()
            front.activate()
            _ = front.wait(for: .runningForeground, timeout: 10)
        case "container":
            front = XCUIApplication(bundleIdentifier: "com.langfour.reader")
            front.activate()
        case "url":
            front = XCUIApplication(bundleIdentifier: "com.apple.mobilesafari")
            front.open(URL(string: arg)!)
        case "tap", "tapif":
            let element = find(arg)
            if element.waitForExistence(timeout: 8) {
                element.tap()
            } else if command == "tap" {
                save(dump: "failed-step-\(index)")
                XCTFail("No element labelled \(arg)")
            }
        case "tapcontains":
            let element = front.descendants(matching: .any)
                .matching(NSPredicate(format: "label CONTAINS[c] %@", arg)).firstMatch
            guard element.waitForExistence(timeout: 8) else {
                save(dump: "failed-step-\(index)")
                return XCTFail("No element containing \(arg)")
            }
            element.tap()
        case "taptext":
            // Captions change every few seconds, so a word can't be named in
            // advance: tap the first text of 3+ letters whose middle lies
            // between the two y values (in points).
            let band = arg.split(separator: ",").compactMap { Double($0) }
            let texts = front.staticTexts.allElementsBoundByIndex
            // Stop at the match: reading every element fails when one of
            // them disappears meanwhile.
            var skip = band.count > 2 ? Int(band[2]) : 0
            let match = texts.first(where: {
                guard $0.label.count >= 3, $0.frame.midY >= band[0], $0.frame.midY <= band[1] else { return false }
                if skip == 0 { return true }
                skip -= 1
                return false
            })
            guard let text = match else {
                save(dump: "failed-step-\(index)")
                return XCTFail("No text between y \(band[0]) and \(band[1])")
            }
            NSLog("TAPTEXT \(text.label)")
            try text.label.write(to: outDir.appendingPathComponent("taptext-\(index).txt"), atomically: true, encoding: .utf8)
            text.tap()
        case "rotate":
            XCUIDevice.shared.orientation = arg == "landscape" ? .landscapeLeft : .portrait
        case "tapxy":
            let xy = arg.split(separator: ",").compactMap { Double($0) }
            front.coordinate(withNormalizedOffset: CGVector(dx: xy[0], dy: xy[1])).tap()
        case "toggle":
            let toggle = front.switches[arg].firstMatch
            guard toggle.waitForExistence(timeout: 8) else {
                save(dump: "failed-step-\(index)")
                return XCTFail("No switch \(arg)")
            }
            if (toggle.value as? String) != "1" { toggle.switches.firstMatch.exists ? toggle.switches.firstMatch.tap() : toggle.tap() }
        case "drag":
            let v = arg.split(separator: ",").compactMap { Double($0) }
            let from = front.coordinate(withNormalizedOffset: CGVector(dx: v[0], dy: v[1]))
            let to = front.coordinate(withNormalizedOffset: CGVector(dx: v[2], dy: v[3]))
            from.press(forDuration: 0.05, thenDragTo: to)
        case "type":
            front.typeText(arg)
        case "backspace":
            front.typeText(String(repeating: XCUIKeyboardKey.delete.rawValue, count: Int(arg) ?? 1))
        case "return":
            front.typeText(XCUIKeyboardKey.return.rawValue)
        case "swipeup":
            front.swipeUp()
        case "swipedown":
            front.swipeDown()
        case "wait":
            Thread.sleep(forTimeInterval: Double(arg) ?? 1)
        case "shot":
            let png = XCUIScreen.main.screenshot().pngRepresentation
            try png.write(to: outDir.appendingPathComponent("\(arg).png"))
        case "dump":
            save(dump: arg)
        default:
            XCTFail("Unknown step \(step)")
        }
    }

    private func find(_ label: String) -> XCUIElement {
        front.descendants(matching: .any)
            .matching(NSPredicate(format: "label == %@ OR identifier == %@", label, label)).firstMatch
    }

    private func save(dump name: String) {
        let text = front.debugDescription
        try? text.write(to: outDir.appendingPathComponent("\(name).txt"), atomically: true, encoding: .utf8)
    }
}
